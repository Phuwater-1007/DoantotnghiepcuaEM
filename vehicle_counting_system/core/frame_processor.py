# ===== file: core/frame_processor.py =====
"""Coordinate single-frame processing: detection -> tracking -> counting -> overlay.

Mục tiêu:
- Chỉ xử lý và đếm trong ROI (vùng mặt đường).
- Có thể crop vùng ROI trước khi detect để giảm tải cho YOLO.
- Không phụ thuộc trực tiếp vào implementation detector/tracker (inject từ ngoài).
"""

from __future__ import annotations

import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    draw_capture_zone,
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
        self._lpr_lock = threading.Lock()

        # Thread pool cho LPR — không block pipeline chính
        self._lpr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lpr")

        # Biến cấu hình LPR Keyframe và chống trùng lặp mới
        self.last_lpr_time = 0.0
        self._lpr_debounce_cache = {}  # plate_text -> timestamp
        self._track_max_bbox_area = {}  # stable_id -> (max_area, frame_with_max_area)
        self._track_keyframe_processed = set()  # stable_id
        self._track_in_capture_start_time = {}  # stable_id -> timestamp
        self._frame_count = 0  # Đếm frame để tối ưu cleanup

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

        # Validate zone positions
        self._validate_zone_positions()

    def _validate_zone_positions(self):
        """Đảm bảo capture zone nằm hợp lý so với counting line."""
        if not self.capture_box_polygon or not self.lines:
            return
        from vehicle_counting_system.utils.logger import get_logger
        _logger = get_logger(__name__)
        capture_center_y = sum(p[1] for p in self.capture_box_polygon) / len(self.capture_box_polygon)
        line_center_y = (self.lines[0][0][1] + self.lines[0][1][1]) / 2
        if capture_center_y > line_center_y:
            _logger.warning(
                "Capture zone (Y=%.0f) nằm SAU counting line (Y=%.0f). "
                "Nên đặt capture zone TRƯỚC line để LPR chạy trước khi đếm.",
                capture_center_y, line_center_y
            )

    @staticmethod
    def _estimate_crop_quality(crop) -> float:
        """Đánh giá chất lượng crop bằng Laplacian variance (độ nét) + diện tích."""
        import cv2
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            h, w = crop.shape[:2]
            area = h * w
            # Score kết hợp: diện tích lớn + ảnh nét = tốt nhất
            return area * min(laplacian_var, 500) / 500.0
        except Exception:
            return 0.0

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

    # ------------------------------------------------------------------
    # Async LPR Worker — chạy trên background thread, KHÔNG block pipeline
    # ------------------------------------------------------------------

    def _crop_vehicle(self, bbox, frame, w_frame, h_frame, class_name: str):
        """Cắt ảnh xe từ bbox, áp dụng padding cho xe máy và trả về (crop, raw_area).
        
        Không upscale ở đây — upscale chỉ chạy 1 lần khi trigger LPR.
        """
        vx1, vy1, vx2, vy2 = bbox
        
        # Nguyên bản diện tích thực tế của xe trong frame
        raw_area = float(max(0.0, vx2 - vx1) * max(0.0, vy2 - vy1))
        
        # Mở rộng padding cho xe máy (biển số thường nằm sát rìa bbox)
        if class_name in {"motorcycle", "bicycle"}:
            pad_x = int((vx2 - vx1) * 0.15)
            pad_y = int((vy2 - vy1) * 0.10)
            vx1 -= pad_x
            vy1 -= pad_y
            vx2 += pad_x
            vy2 += pad_y
            
        vx1 = max(0, int(vx1))
        vy1 = max(0, int(vy1))
        vx2 = min(w_frame, int(vx2))
        vy2 = min(h_frame, int(vy2))
        
        w = vx2 - vx1
        h = vy2 - vy1
        
        # Giảm ngưỡng kích thước tối thiểu cho xe máy
        min_size = 15 if class_name in {"motorcycle", "bicycle"} else 20
        if w < min_size or h < min_size:
            return None, 0.0
            
        crop = frame[vy1:vy2, vx1:vx2].copy()
        return crop, raw_area

    def _smart_upscale(self, crop, class_name: str):
        """Zoom thông minh cho xe nhỏ — CHỈ gọi khi trigger LPR (không mỗi frame).
        
        Dùng INTER_CUBIC (nhanh hơn LANCZOS4 ~3x, chất lượng đủ tốt cho OCR).
        """
        if crop is None or crop.size == 0:
            return crop
            
        try:
            import cv2
            h, w = crop.shape[:2]
            
            # Target: đảm bảo chiều rộng crop >= 200px cho LPR
            target_width = 200 if class_name in {"motorcycle", "bicycle"} else 250
            
            if w < target_width:
                scale = target_width / w
                scale = min(scale, 4.0)
                crop = cv2.resize(crop, (0, 0), fx=scale, fy=scale, 
                                  interpolation=cv2.INTER_CUBIC)
                # Sharpen sau khi upscale
                gaussian = cv2.GaussianBlur(crop, (0, 0), 1.2)
                crop = cv2.addWeighted(crop, 1.5, gaussian, -0.5, 0)
        except Exception:
            pass
        return crop

    def _preprocess_lpr_image(self, image):
        """Tiền xử lý ảnh cho LPR: Tăng sáng (Gamma 1.4) + CLAHE tương phản + Zoom Cubic."""
        if image is None or image.size == 0:
            return image
        
        try:
            import cv2

            # 1. Gamma Correction để làm sáng vùng biển bị tối/bóng râm
            image = self._adjust_gamma(image, gamma=1.4)

            # 2. CLAHE tăng tương phản thích ứng giúp nổi bật các ký tự chữ/số
            image = self._apply_clahe(image)
            
            # 3. Phóng to nếu ảnh quá bé (CUBIC nhanh và giữ nét tốt cho OCR)
            h, w = image.shape[:2]
            if w < 150:
                scale = 200.0 / w
                image = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                gaussian = cv2.GaussianBlur(image, (0, 0), 1.5)
                image = cv2.addWeighted(image, 1.6, gaussian, -0.6, 0)
        except Exception:
            pass
        return image

    def _adjust_gamma(self, image, gamma=1.4):
        import numpy as np
        import cv2
        invGamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        return cv2.LUT(image, table)

    def _apply_clahe(self, image):
        import cv2
        if len(image.shape) == 3:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            return clahe.apply(image)

    def _get_lpr_on_crop(self, vehicle_crop, class_name="unknown") -> tuple[str, float, np.ndarray, np.ndarray] | None:
        """Nhận diện biển số trên 1 crop. Trả về (plate_text, final_conf, vehicle_crop, plate_crop) hoặc None."""
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        # Upscale ở đây (chỉ 1 lần khi trigger LPR, không phải mỗi frame)
        vehicle_crop = self._smart_upscale(vehicle_crop, class_name)

        # Tiền xử lý
        preprocessed_vehicle = self._preprocess_lpr_image(vehicle_crop)
        
        if self.lpr_service.detector is None:
            return None
            
        try:
            results = self.lpr_service.detector.predict(preprocessed_vehicle, verbose=False, conf=0.25)
        except Exception:
            return None
        
        best_plate_box = None
        best_plate_conf = 0.0
        
        for r in results:
            if not r.boxes:
                continue
            for box in r.boxes:
                conf = float(box.conf[0])
                if conf > best_plate_conf:
                    best_plate_conf = conf
                    best_plate_box = box.xyxy[0].cpu().numpy()
        
        lpr_quality_th = getattr(settings, "lpr_quality_threshold", 0.20)
        if best_plate_box is not None and best_plate_conf >= lpr_quality_th:
            px1, py1, px2, py2 = best_plate_box
            pad_x = int((px2 - px1) * 0.08)
            pad_y = int((py2 - py1) * 0.10)
            cpx1 = max(0, int(px1) - pad_x)
            cpy1 = max(0, int(py1) - pad_y)
            cpx2 = min(vehicle_crop.shape[1], int(px2) + pad_x)
            cpy2 = min(vehicle_crop.shape[0], int(py2) + pad_y)
            
            plate_crop = vehicle_crop[cpy1:cpy2, cpx1:cpx2]
            if plate_crop.size > 0:
                res_ocr = self.lpr_service.run_ocr(plate_crop, vehicle_class=class_name)
                if res_ocr:
                    plate_text, ocr_conf = res_ocr
                    if ocr_conf >= 0.35:  # Ngưỡng tối thiểu độ tự tin OCR để lọc bỏ biển mờ/rác
                        final_conf = (best_plate_conf * 0.4) + (ocr_conf * 0.6)
                        return plate_text, final_conf, vehicle_crop, plate_crop
        return None

    def _process_lpr_for_vehicle(self, lpr_key, state, current_time, class_name="unknown") -> None:
        """Multi-attempt LPR: chạy nhận diện trên cả 3 crops, bỏ phiếu chọn kết quả tốt nhất."""
        best_crops = state.get("best_crops", [])
        
        # Fallback: nếu không có multi-crop, thử crop đơn (tương thích ngược)
        if not best_crops:
            vehicle_crop = state.get("best_vehicle_crop")
            if vehicle_crop is not None and vehicle_crop.size > 0:
                best_crops = [(0.0, vehicle_crop)]
        
        if not best_crops:
            with self._lpr_lock:
                state["is_finalized"] = False
            return
        
        # Sắp xếp theo quality giảm dần, lấy tối đa 3 crops tốt nhất
        best_crops.sort(key=lambda x: x[0], reverse=True)
        
        candidates = []
        for item in best_crops[:3]:
            # Hỗ trợ cả định dạng tuple 2 phần tử (quality, crop) và 3 phần tử (quality, crop, frame_idx)
            vehicle_crop = item[1]
            res = self._get_lpr_on_crop(vehicle_crop, class_name)
            if res is not None:
                candidates.append(res) # res: (plate_text, final_conf, vehicle_crop, plate_crop)
                
        if not candidates:
            with self._lpr_lock:
                state["is_finalized"] = False
            return
            
        # Thực hiện bỏ phiếu (Voting) trên các ứng viên
        votes = {}
        for plate_text, final_conf, v_crop, p_crop in candidates:
            norm = self.lpr_service.normalize_plate(plate_text)
            if not norm:
                continue
            if norm not in votes:
                votes[norm] = {
                    "raw_text": plate_text,
                    "count": 0,
                    "confs": [],
                    "v_crop": v_crop,
                    "p_crop": p_crop
                }
            votes[norm]["count"] += 1
            votes[norm]["confs"].append(final_conf)
            
        if not votes:
            with self._lpr_lock:
                state["is_finalized"] = False
            return
            
        # Tìm biển số chiến thắng theo phiếu bầu cao nhất
        winner_norm = None
        winner_data = None
        max_votes = -1
        max_avg_conf = -1.0
        
        for norm, data in votes.items():
            avg_conf = sum(data["confs"]) / len(data["confs"])
            if data["count"] > max_votes or (data["count"] == max_votes and avg_conf > max_avg_conf):
                max_votes = data["count"]
                max_avg_conf = avg_conf
                winner_norm = norm
                winner_data = data
                
        winning_raw_text = winner_data["raw_text"]
        winning_v_crop = winner_data["v_crop"]
        winning_p_crop = winner_data["p_crop"]
        
        # Kiểm tra trùng lặp trong cache debounce
        if winner_norm in self._lpr_debounce_cache:
            with self._lpr_lock:
                state["plate_text"] = winning_raw_text
                self._track_lpr_results[lpr_key] = winning_raw_text
                state["is_finalized"] = True
            return
            
        self._lpr_debounce_cache[winner_norm] = current_time
        
        # Định dạng biển số hiển thị
        is_motorcycle = class_name in ["motorcycle", "bicycle", "tricycle"]
        formatted_text = self.lpr_service.format_vietnamese_plate(winning_raw_text, is_motorcycle=is_motorcycle)
        
        with self._lpr_lock:
            state["plate_text"] = formatted_text
            self._track_lpr_results[lpr_key] = formatted_text
            state["is_finalized"] = True
            
        # Lưu ảnh crop và kích hoạt callback hiển thị
        rel_vehicle, rel_plate = self.lpr_service.save_cropped_images(
            winning_v_crop, winning_p_crop, lpr_key, self.session_id
        )
        self._trigger_lpr_callback(
            lpr_key, class_name, formatted_text, max_avg_conf, rel_vehicle, rel_plate
        )


    def _run_inference(self, frame) -> tuple[List[TrackedObject], object]:
        """Run detect -> track -> smooth classification -> count."""
        import time
        
        self._frame_count += 1
        detections = self._detect_with_optional_crop(frame)
        tracks: List[TrackedObject] = self.tracker.update(detections)
        tracks = self.classifier.classify(tracks)
        stats = self.counter.process(tracks) # Đếm xe độc lập dựa trên vạch đếm

        h_frame, w_frame = frame.shape[:2]
        current_time = time.time()
        
        # Dọn dẹp cache chống trùng lặp — chỉ mỗi 30 frame để giảm overhead
        if self._frame_count % 30 == 0:
            debounce_limit = getattr(settings, "lpr_debounce_seconds", 60)
            self._lpr_debounce_cache = {
                k: v for k, v in self._lpr_debounce_cache.items() 
                if (current_time - v) < debounce_limit
            }

        # Thu thập các active lpr_keys ở frame hiện tại
        active_lpr_keys = set()
        for tr in tracks:
            lpr_key = tr.stable_id if tr.stable_id is not None else tr.track_id
            active_lpr_keys.add(lpr_key)

        # A. Kiểm tra các xe đã biến mất khỏi camera khi đang ở trong Capture Zone
        for old_key, was_in in list(self._track_in_capture_last.items()):
            if was_in and old_key not in active_lpr_keys:
                # Xe đã biến mất -> Kích hoạt LPR ngay
                self._track_in_capture_last[old_key] = False
                state = self._track_lpr_results.get(old_key)
                if state and not state["is_finalized"] and state["plate_text"] is None:
                    state["is_finalized"] = True
                    class_name = state.get("class_name", "unknown")
                    self._process_lpr_for_vehicle(old_key, state, current_time, class_name=class_name)

        # B. Xử lý LPR theo chuyển động cho các xe đang hoạt động
        for tr in tracks:
            # Gán display_id tuần tự chỉ khi xe thực sự đi vào vùng ROI
            ax, ay = get_bbox_bottom_center(tr.bbox)
            if _point_in_polygon((int(ax), int(ay)), self.roi_polygon):
                if hasattr(self.tracker, "get_or_assign_display_id"):
                    self.tracker.get_or_assign_display_id(tr.track_id)

            lpr_key = tr.stable_id if tr.stable_id is not None else tr.track_id
            
            # Khởi tạo state nếu chưa có
            with self._lpr_lock:
                state = self._track_lpr_results.get(lpr_key)
                if state is None or not isinstance(state, dict):
                    state = {
                        "plate_text": None,
                        "best_crops": [],       # List of (quality_score, crop) — top 3
                        "best_vehicle_crop": None,  # Tương thích ngược
                        "is_finalized": False,
                        "class_name": tr.class_name,
                        "frames_in_zone": 0,
                    }
                    self._track_lpr_results[lpr_key] = state
                else:
                    state["class_name"] = tr.class_name
                
                # Đồng bộ biển số đã nhận diện sang track object để vẽ lên màn hình
                if state.get("plate_text"):
                    tr.license_plate = state["plate_text"]
                else:
                    tr.license_plate = None

            # Bỏ qua xe có lớp không được đếm trong settings
            if self.counter._allowed_names and tr.class_name not in self.counter._allowed_names:
                continue

            # Kiểm tra xem xe có trong Capture Zone ở frame này hay không
            in_capture = _point_in_polygon((int(ax), int(ay)), self.capture_box_polygon)
            was_in_capture = self._track_in_capture_last.get(lpr_key, False)
            self._track_in_capture_last[lpr_key] = in_capture

            # 1. Nếu xe đang trong Capture Zone -> Theo dõi đồ thị chất lượng để bắt điểm Đỉnh (Peak)
            if in_capture and not state["is_finalized"] and state["plate_text"] is None:
                state["frames_in_zone"] = state.get("frames_in_zone", 0) + 1
                crop, raw_area = self._crop_vehicle(tr.bbox, frame, w_frame, h_frame, tr.class_name)
                if crop is not None:
                    quality = self._estimate_crop_quality(crop)
                    
                    # Khởi tạo các giá trị đỉnh nếu chưa có
                    if "peak_quality" not in state:
                        state["peak_quality"] = 0.0
                        state["peak_crop"] = None
                        state["quality_history"] = []
                        state["consecutive_drops"] = 0

                    state["quality_history"].append(quality)
                    
                    # Nếu chất lượng hiện tại tốt hơn đỉnh cũ -> Cập nhật đỉnh mới
                    if quality > state["peak_quality"]:
                        state["peak_quality"] = quality
                        state["peak_crop"] = crop
                        state["consecutive_drops"] = 0
                    else:
                        # Nếu chất lượng giảm so với frame trước -> Đếm số lần giảm liên tiếp
                        state["consecutive_drops"] += 1

                    # Cập nhật để tương thích ngược với luồng lưu ảnh
                    state["best_vehicle_crop"] = state["peak_crop"]
                    current_frame_idx = self._frame_count
                    if not state.get("best_crops"):
                        state["best_crops"] = [(quality, crop, current_frame_idx)]
                    else:
                        # Đảm bảo các ảnh trong top 3 cách nhau ít nhất 3 frames để đa dạng góc chụp/vị trí
                        is_diverse = True
                        for _, _, f_idx in state["best_crops"]:
                            if abs(current_frame_idx - f_idx) < 3:
                                is_diverse = False
                                break
                        
                        if is_diverse:
                            state["best_crops"].append((quality, crop, current_frame_idx))
                            state["best_crops"].sort(key=lambda x: x[0], reverse=True)
                            state["best_crops"] = state["best_crops"][:3]
                        else:
                            # Nếu không đa dạng (quá gần), cập nhật ảnh cũ nếu chất lượng tốt hơn
                            for idx, (q, c, f_idx) in enumerate(state["best_crops"]):
                                if abs(current_frame_idx - f_idx) < 3 and quality > q:
                                    state["best_crops"][idx] = (quality, crop, current_frame_idx)
                                    state["best_crops"].sort(key=lambda x: x[0], reverse=True)
                                    break

                    # THƯƠNG MẠI: Nếu đã ở trong zone > 5 frames và chất lượng giảm liên tiếp 3 frames 
                    # (chứng tỏ đã đi qua điểm nét nhất - Điểm Đỉnh) -> Kích hoạt LPR ngay lập tức!
                    if state["frames_in_zone"] >= 6 and state["consecutive_drops"] >= 3 and state["peak_quality"] > 3000:
                        state["is_finalized"] = True
                        self._lpr_executor.submit(
                            self._process_lpr_for_vehicle, lpr_key, state, current_time, class_name=tr.class_name
                        )

            # 2. Nếu xe đi ra khỏi Capture Zone -> Kích hoạt LPR async bằng ảnh Đỉnh (Peak Crop) rõ nhất
            exited_zone = was_in_capture and not in_capture
            if exited_zone and not state["is_finalized"] and state["plate_text"] is None:
                state["is_finalized"] = True
                
                # Sử dụng ảnh đỉnh (peak crop) thu thập được, nếu không có mới crop ở frame hiện tại
                peak_crop = state.get("peak_crop")
                if peak_crop is not None:
                    state["best_vehicle_crop"] = peak_crop
                elif not state.get("best_crops") and state.get("best_vehicle_crop") is None:
                    crop, raw_area = self._crop_vehicle(tr.bbox, frame, w_frame, h_frame, tr.class_name)
                    if crop is not None:
                        state["best_vehicle_crop"] = crop
                        
                # LPR chạy async trên background thread
                self._lpr_executor.submit(
                    self._process_lpr_for_vehicle, lpr_key, state, current_time, class_name=tr.class_name
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
        
        # Vẽ Capture Zone bằng style riêng biệt (tím nhạt, dashed border)
        if self.capture_box_polygon:
            draw_capture_zone(frame, self.capture_box_polygon)

        if settings.show_stats:
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
        """Cập nhật filter loại xe được đếm. Luôn đảm bảo giữ lại các lớp chính."""
        from vehicle_counting_system.configs.settings import settings as _settings
        base_allowed = {"motorcycle", "car", "truck", "bus"}
        if classes is None or not classes:
            self.counter._allowed_names = base_allowed
        else:
            # Chỉ cho phép lọc trong tập hợp xe hợp lệ, tránh lỗi rỗng
            self.counter._allowed_names = set(classes).intersection(base_allowed)
            if not self.counter._allowed_names:
                self.counter._allowed_names = base_allowed

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
        with self._lpr_lock:
            self._track_lpr_results.clear()
        self._track_ocr_history.clear()
        self._track_in_capture_last.clear()
        
        # Reset các biến LPR Keyframe và chống trùng lặp mới
        self.last_lpr_time = 0.0
        self._lpr_debounce_cache.clear()
        self._track_max_bbox_area.clear()
        self._track_keyframe_processed.clear()
        self._track_in_capture_start_time.clear()

    def close(self) -> None:
        try:
            if hasattr(self.detector, "close"):
                self.detector.close()
        except Exception:
            pass
        # Shutdown LPR thread pool
        try:
            self._lpr_executor.shutdown(wait=False)
        except Exception:
            pass
        self.reset()
