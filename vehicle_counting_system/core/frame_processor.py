# ===== file: core/frame_processor.py =====
"""Coordinate single-frame processing: detection -> tracking -> counting -> overlay.

Mục tiêu:
- Chỉ xử lý và đếm trong ROI (vùng mặt đường).
- Có thể crop vùng ROI trước khi detect để giảm tải cho YOLO.
- Không phụ thuộc trực tiếp vào implementation detector/tracker (inject từ ngoài).
"""

from __future__ import annotations

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
    ):
        # Detector/tracker được inject từ ngoài để giữ module này độc lập.
        self.detector = detector
        self.tracker = tracker

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

    def _run_inference(self, frame) -> tuple[List[TrackedObject], object]:
        """Run detect -> ROI filter -> track -> smooth classification -> count."""
        detections = self._detect_with_optional_crop(frame)
        detections = self._filter_by_roi(detections)
        tracks: List[TrackedObject] = self.tracker.update(detections)
        tracks = self.classifier.classify(tracks)
        stats = self.counter.process(tracks)
        self.last_stats = stats
        return tracks, stats

    def _render_overlay(self, frame, tracks: List[TrackedObject], stats) -> None:
        alpha = getattr(settings, "display_smooth_alpha", 0.0)
        active_ids = {tr.track_id for tr in tracks}
        for tr in tracks:
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
            # Optional: label first line as "L1" to help debugging.
            if idx == 0:
                line_label = "L1"
            draw_counting_line(frame, start, end, label=line_label)

        draw_roi_polygon(frame, self.roi_polygon)

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

    def close(self) -> None:
        try:
            if hasattr(self.detector, "close"):
                self.detector.close()
        except Exception:
            pass
        self.reset()
