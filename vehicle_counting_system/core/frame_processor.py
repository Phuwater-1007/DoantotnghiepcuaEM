# ===== file: core/frame_processor.py =====
"""Coordinate single-frame processing: detection -> tracking -> counting -> overlay.

Mục tiêu:
- Chỉ xử lý và đếm trong ROI (vùng mặt đường).
- Có thể crop vùng ROI trước khi detect để giảm tải cho YOLO.
- Không phụ thuộc trực tiếp vào implementation detector/tracker (inject từ ngoài).
"""

from __future__ import annotations

import re
import time
from typing import List, Tuple, Optional

from vehicle_counting_system.counters.line_counter import LineCounter
from vehicle_counting_system.configs.counting_config import load_counting_config
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.classifiers.vehicle_classifier import VehicleClassifier
from vehicle_counting_system.models.detection import Detection
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.utils.math_utils import get_bbox_bottom_center
from vehicle_counting_system.utils.vision_utils import (
    draw_track,
    draw_counting_line,
    draw_statistics,
    draw_roi_polygon,
    sharpen_frame,
)
from vehicle_counting_system.ai_core.services.lpr_service import LPRService
from vehicle_counting_system.application.services.lpr_persistence_service import LPREvent


Point = Tuple[int, int]


def _point_in_polygon(pt: Point, polygon: List[Point]) -> bool:
    """Kiểm tra point nằm trong đa giác (thuật toán even-odd)."""
    if not polygon:
        return True
    x, y = pt
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1
        ):
            inside = not inside
    return inside


class FrameProcessor:
    def __init__(
        self,
        detector,
        tracker,
        counting_lines_path: Optional[str] = None,
        frame_size: Optional[Tuple[int, int]] = None,
        counting_persistence_callback=None,
        lpr_persistence_callback=None,
    ):
        # Detector/tracker được inject từ ngoài để giữ module này độc lập.
        self.detector = detector
        self.tracker = tracker
        self.session_id = 0
        self._lpr_persistence_callback = lpr_persistence_callback

        cfg = load_counting_config(counting_lines_path, frame_size=frame_size)

        self.lines: List[Tuple[Point, Point]] = []
        self.line_directions: List[str] = []
        for line in cfg.get("lines", []):
            self.lines.append(
                (
                    (int(line["start"][0]), int(line["start"][1])),
                    (int(line["end"][0]), int(line["end"][1])),
                )
            )
            self.line_directions.append(str(line.get("direction", "both")).lower())

        # ROI có thể là list các point [[x1,y1], [x2,y2], ...].
        raw_roi = cfg.get("roi") or []
        self.roi_polygon: List[Point] = [
            (int(p[0]), int(p[1])) for p in raw_roi
        ]

        # Bounding box thô bao quanh ROI để có thể crop ảnh đầu vào.
        if self.roi_polygon:
            xs = [p[0] for p in self.roi_polygon]
            ys = [p[1] for p in self.roi_polygon]
            self.roi_bbox = (min(xs), min(ys), max(xs), max(ys))
        else:
            self.roi_bbox = None

        self.counter = LineCounter(self.lines, line_directions=self.line_directions)
        self.classifier = VehicleClassifier()
        self.last_stats = None
        self._last_ts = time.perf_counter()
        self._fps_ema: float | None = None
        self._smoothed_bbox: dict[int, Tuple[float, float, float, float]] = {}
        self._counting_persistence_callback = counting_persistence_callback

        # Khởi tạo LPR Service và cấu hình Capture Box
        self.lpr_service = LPRService(use_gpu=getattr(settings, "use_gpu", True))
        self._track_lpr_results = {}
        self._track_ocr_history = {}
        self._track_in_capture_last = {}

        self.capture_box_polygon = []
        raw_capture_box = cfg.get("lpr_zone") or cfg.get("capture_box")
        if raw_capture_box:
            self.capture_box_polygon = [(int(p[0]), int(p[1])) for p in raw_capture_box]
        elif len(self.roi_polygon) >= 4:
            # Tự động tính Capture Box là 60% phần dưới của ROI
            r = self.roi_polygon
            t = 0.4
            p_top_left = (int((1 - t) * r[0][0] + t * r[3][0]), int((1 - t) * r[0][1] + t * r[3][1]))
            p_top_right = (int((1 - t) * r[1][0] + t * r[2][0]), int((1 - t) * r[1][1] + t * r[2][1]))
            self.capture_box_polygon = [p_top_left, p_top_right, r[2], r[3]]
        else:
            self.capture_box_polygon = self.roi_polygon

    def _filter_by_roi(self, detections: List[Detection]) -> List[Detection]:
        if not self.roi_polygon:
            return detections
        filtered: List[Detection] = []
        for det in detections:
            ax, ay = get_bbox_bottom_center(det.bbox)
            if _point_in_polygon((int(ax), int(ay)), self.roi_polygon):
                filtered.append(det)
        return filtered

    def _detect_with_optional_crop(self, frame) -> List[Detection]:
        """
        Ưu tiên chất lượng bbox: với RTX 3050, chạy YOLO trên full-frame,
        chỉ dùng ROI để lọc sau detect chứ không crop, tránh biến dạng box.
        """
        return self.detector.detect(frame)

    def _trigger_lpr_callback(self, track_id: int, vehicle_class: str, plate_text: str, confidence: float, vehicle_path: str, plate_path: str):
        if self._lpr_persistence_callback is not None:
            try:
                event = LPREvent(
                    track_id=track_id,
                    vehicle_class=vehicle_class,
                    license_plate=plate_text,
                    confidence=confidence,
                    vehicle_image_path=vehicle_path,
                    plate_image_path=plate_path
                )
                self._lpr_persistence_callback(event)
            except Exception:
                pass

    def _run_inference(self, frame) -> tuple[List[TrackedObject], object]:
        """Run detect -> track -> smooth classification -> count."""
        detections = self._detect_with_optional_crop(frame)
        # Bỏ lọc ROI trước khi track để thực hiện Global Tracking (ByteTrack ổn định hơn)
        tracks: List[TrackedObject] = self.tracker.update(detections)
        tracks = self.classifier.classify(tracks)
        stats = self.counter.process(tracks)

        h_frame, w_frame = frame.shape[:2]
        allowed_classes = {"car", "truck", "bus", "motorcycle"}

        # Chạy nhận diện biển số xe (LPR) theo thuật toán Quality-Aware Multi-Frame Voting
        for tr in tracks:
            state = self._track_lpr_results.get(tr.track_id)
            if state is None:
                state = {
                    "plate_text": None,
                    "confidence": 0.0,
                    "vehicle_path": None,
                    "plate_path": None,
                    "is_finalized": False,
                    "best_score": 0.0,
                    "best_plate_crop": None,
                    "best_vehicle_crop": None,
                    "best_det_conf": 0.0
                }
                self._track_lpr_results[tr.track_id] = state

            if state.get("plate_text"):
                tr.license_plate = state["plate_text"]
            else:
                tr.license_plate = None

            if tr.class_name not in allowed_classes:
                continue

            ax, ay = get_bbox_bottom_center(tr.bbox)
            in_capture = _point_in_polygon((int(ax), int(ay)), self.capture_box_polygon)
            was_in_capture = self._track_in_capture_last.get(tr.track_id, False)
            self._track_in_capture_last[tr.track_id] = in_capture

            if state["is_finalized"]:
                continue

            # 1. Xe đang trong vùng Capture Box -> Quét và tích lũy các kết quả nhận diện biển số
            if in_capture:
                vx1, vy1, vx2, vy2 = tr.bbox
                vx1 = max(0, int(vx1))
                vy1 = max(0, int(vy1))
                vx2 = min(w_frame, int(vx2))
                vy2 = min(h_frame, int(vy2))
                if (vx2 - vx1) >= 20 and (vy2 - vy1) >= 20:
                    vehicle_crop = frame[vy1:vy2, vx1:vx2]
                    res_det = self.lpr_service.detect_plate_box(vehicle_crop)
                    if res_det:
                        plate_crop, det_conf = res_det
                        
                        # Tính toán điểm chất lượng để theo dõi khung hình tốt nhất
                        h_p, w_p = plate_crop.shape[:2]
                        area_at = float(h_p * w_p)
                        a_max_expected = 15000.0
                        normalized_area = min(1.0, area_at / a_max_expected)
                        score = 0.7 * det_conf + 0.3 * normalized_area
                        
                        if score > state["best_score"]:
                            state["best_score"] = score
                            state["best_plate_crop"] = plate_crop
                            state["best_vehicle_crop"] = vehicle_crop
                            state["best_det_conf"] = det_conf

                        # Chạy nhận diện OCR và tích lũy vào lịch sử bỏ phiếu nếu độ tin cậy detector ổn (> 0.20)
                        if det_conf > 0.20:
                            res_ocr = self.lpr_service.run_ocr(plate_crop)
                            if res_ocr:
                                plate_text, ocr_conf = res_ocr
                                final_conf = (det_conf * 0.4) + (ocr_conf * 0.6)
                                rel_vehicle, rel_plate = self.lpr_service.save_cropped_images(
                                    vehicle_crop, plate_crop, tr.track_id, self.session_id
                                )
                                
                                if tr.track_id not in self._track_ocr_history:
                                    self._track_ocr_history[tr.track_id] = []
                                
                                self._track_ocr_history[tr.track_id].append({
                                    "plate_text": plate_text,
                                    "confidence": final_conf,
                                    "vehicle_path": rel_vehicle,
                                    "plate_path": rel_plate
                                })

                                # Thực hiện thuật toán Bỏ Phiếu (Voting / Aggregation)
                                # Regex validate biển số VN: 2 số + 1-2 chữ + 4-5 số
                                _VN_PLATE_RE = re.compile(r'^\d{2}[A-Z]{1,2}\d{4,5}$')
                                history = self._track_ocr_history[tr.track_id]
                                votes = {}
                                for entry in history:
                                    norm_text = entry["plate_text"].replace(" ", "").replace("-", "").replace(".", "").upper()
                                    # Lọc bỏ kết quả không đúng format biển VN
                                    if not _VN_PLATE_RE.match(norm_text):
                                        continue
                                    if norm_text not in votes:
                                        votes[norm_text] = []
                                    votes[norm_text].append(entry)

                                # Tìm kết quả có điểm tích lũy (tần suất * độ tin cậy trung bình) cao nhất
                                best_norm = None
                                best_vote_score = -1.0
                                for norm, entries in votes.items():
                                    freq = len(entries)
                                    avg_conf = sum(e["confidence"] for e in entries) / freq
                                    v_score = freq * avg_conf
                                    if v_score > best_vote_score:
                                        best_vote_score = v_score
                                        best_norm = norm

                                if best_norm:
                                    best_entry = max(votes[best_norm], key=lambda e: e["confidence"])
                                    
                                    # Cập nhật kết quả tốt nhất hiện tại lên DB và UI
                                    if state["plate_text"] != best_entry["plate_text"] or best_entry["confidence"] > state["confidence"]:
                                        state.update({
                                            "plate_text": best_entry["plate_text"],
                                            "confidence": best_entry["confidence"],
                                            "vehicle_path": best_entry["vehicle_path"],
                                            "plate_path": best_entry["plate_path"]
                                        })
                                        tr.license_plate = best_entry["plate_text"]
                                        self._trigger_lpr_callback(
                                            tr.track_id, tr.class_name, best_entry["plate_text"],
                                            best_entry["confidence"], best_entry["vehicle_path"], best_entry["plate_path"]
                                        )

                                    # Tối ưu hóa: YOLO char chính xác hơn EasyOCR → chỉ cần 2 lần trùng để finalize
                                    if len(votes[best_norm]) >= 2 and (sum(e["confidence"] for e in votes[best_norm]) / len(votes[best_norm])) >= 0.65:
                                        state["is_finalized"] = True

            # 2. Cơ chế Fallback / Finalization: Xe đi ra khỏi vùng tím hoặc cắt qua vạch đếm
            exited_zone = was_in_capture and not in_capture
            crossed_line = False
            for key in self.counter._counted:
                if key[0] == tr.track_id:
                    crossed_line = True
                    break

            if (exited_zone or crossed_line) and not state["is_finalized"]:
                state["is_finalized"] = True
                
                # Nếu chưa chạy OCR được khung hình nào, tiến hành chạy fallback trên khung hình có điểm chất lượng YOLO cao nhất lưu được
                if (tr.track_id not in self._track_ocr_history or not self._track_ocr_history[tr.track_id]) and state["best_plate_crop"] is not None:
                    plate_crop = state["best_plate_crop"]
                    vehicle_crop = state["best_vehicle_crop"]
                    det_conf = state["best_det_conf"]
                    
                    res_ocr = self.lpr_service.run_ocr(plate_crop)
                    if res_ocr:
                        plate_text, ocr_conf = res_ocr
                        final_conf = (det_conf * 0.4) + (ocr_conf * 0.6)
                        rel_vehicle, rel_plate = self.lpr_service.save_cropped_images(
                            vehicle_crop, plate_crop, tr.track_id, self.session_id
                        )
                        state.update({
                            "plate_text": plate_text,
                            "confidence": final_conf,
                            "vehicle_path": rel_vehicle,
                            "plate_path": rel_plate
                        })
                        tr.license_plate = plate_text
                        self._trigger_lpr_callback(
                            tr.track_id, tr.class_name, plate_text, final_conf, rel_vehicle, rel_plate
                        )

        # Forward counting events to persistence layer (nếu có).
        if self._counting_persistence_callback and self.counter.pending_events:
            for event in self.counter.pending_events:
                try:
                    self._counting_persistence_callback(event)
                except Exception:
                    pass
            self.counter.pending_events.clear()
        self.last_stats = stats
        return tracks, stats

    def _render_overlay(self, frame, tracks: List[TrackedObject], stats) -> None:
        alpha = getattr(settings, "display_smooth_alpha", 0.0)
        active_ids = {tr.track_id for tr in tracks}
        
        # Chỉ hiển thị bounding box của phương tiện nằm bên trong ROI
        visible_tracks = []
        for tr in tracks:
            ax, ay = get_bbox_bottom_center(tr.bbox)
            if _point_in_polygon((int(ax), int(ay)), self.roi_polygon):
                visible_tracks.append(tr)

        for tr in visible_tracks:
            bbox_override = None
            if alpha > 0:
                raw = tr.bbox
                prev = self._smoothed_bbox.get(tr.track_id)
                if prev is None:
                    smoothed = raw
                else:
                    smoothed = tuple(
                        alpha * r + (1.0 - alpha) * p
                        for r, p in zip(raw, prev)
                    )
                self._smoothed_bbox[tr.track_id] = smoothed
                bbox_override = smoothed
            draw_track(
                frame,
                tr,
                show_center=settings.show_track_center,
                show_label=settings.show_labels,
                bbox_override=bbox_override,
            )
        if alpha > 0:
            for tid in list(self._smoothed_bbox.keys()):
                if tid not in active_ids:
                    del self._smoothed_bbox[tid]

        for idx, (start, end) in enumerate(self.lines):
            line_label = None
            if idx == 0:
                line_label = "L1"
            draw_counting_line(frame, start, end, label=line_label)

        draw_roi_polygon(frame, self.roi_polygon)
        
        # Vẽ Capture Box bằng màu tím hồng để người dùng dễ quan sát
        if self.capture_box_polygon:
            draw_roi_polygon(frame, self.capture_box_polygon, color=(255, 0, 255))

        draw_statistics(
            frame,
            {"total": stats.total, **stats.per_class},
        )

    def _draw_fps(self, frame, started_at: float) -> None:
        # FPS (EMA for stable display)
        dt = max(1e-6, started_at - self._last_ts)
        inst_fps = 1.0 / dt
        self._last_ts = started_at
        if self._fps_ema is None:
            self._fps_ema = inst_fps
        else:
            self._fps_ema = 0.9 * self._fps_ema + 0.1 * inst_fps

        try:
            import cv2

            cv2.putText(
                frame,
                f"FPS: {self._fps_ema:.1f}",
                (10, frame.shape[0] - 12),
                cv2.FONT_HERSHEY_DUPLEX,
                0.75,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        except Exception:
            pass

    def set_active_classes(self, classes: set | None) -> None:
        """Cập nhật filter loại xe được đếm trong khi stream đang chạy.

        Args:
            classes: Set tên class cần đếm (vd: {"car", "motorcycle"}).
                     None = đếm tất cả class được phép trong settings.
        """
        from vehicle_counting_system.configs.settings import settings as _settings
        if classes is None:
            self.counter._allowed_names = set(_settings.allowed_class_names)
        else:
            self.counter._allowed_names = set(classes)

    def process(self, frame):
        started_at = time.perf_counter()
        tracks, stats = self._run_inference(frame)
        self._render_overlay(frame, tracks, stats)
        self._draw_fps(frame, started_at)
        amount = getattr(settings, "video_sharpen", 0.4)
        if amount > 0:
            frame = sharpen_frame(frame, amount)
        return frame

    def reset(self) -> None:
        # Allow reusing the same processor object across runs.
        try:
            if hasattr(self.tracker, "reset"):
                self.tracker.reset()
        except Exception:
            pass
        try:
            if hasattr(self.counter, "reset"):
                self.counter.reset()
        except Exception:
            pass
        try:
            if hasattr(self.classifier, "reset"):
                self.classifier.reset()
        except Exception:
            pass
        self.last_stats = None
        self._last_ts = time.perf_counter()
        self._fps_ema = None
        self._smoothed_bbox.clear()
        self._track_lpr_results.clear()
        self._track_ocr_history.clear()
        self._track_in_capture_last.clear()

    def close(self) -> None:
        try:
            if hasattr(self.detector, "close"):
                self.detector.close()
        except Exception:
            pass
        self.reset()
