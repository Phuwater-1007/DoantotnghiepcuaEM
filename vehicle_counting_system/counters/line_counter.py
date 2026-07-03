# ===== file: counters/line_counter.py =====
"""Count objects crossing configured lines using bottom-center trajectory.

V2 — Cải tiến cho stable tracking:
- Sử dụng stable_id thay vì track_id để chống đếm trùng khi Re-ID
- Giảm Moving Average window 5→3 frame để phản ứng nhanh hơn
- Bỏ jitter filter 3px (đang chặn quá nhiều crossing hợp lệ)
- Spatial-Temporal Debounce thông minh hơn
"""

import math
from dataclasses import dataclass, field
import time
from typing import Dict, List, Tuple

from vehicle_counting_system.counters.base_counter import BaseCounter
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.utils.math_utils import line_intersection


@dataclass
class CountEvent:
    """Sự kiện xe vừa được đếm qua counting line."""
    track_id: int
    class_name: str
    confidence: float
    direction: str
    line_index: int
    anchor_x: float
    anchor_y: float
    timestamp: float = field(default_factory=time.time)


class LineCounter(BaseCounter):
    def __init__(
        self,
        lines: List[Tuple[Tuple[int, int], Tuple[int, int]]],
        *,
        line_directions: List[str] | None = None,
    ):
        super().__init__()
        self.lines = lines
        self.line_directions = line_directions or ["both"] * len(lines)
        # Bộ đệm lưu trữ quỹ đạo thô để làm mịn: stable_id -> List[Tuple[float, float]]
        self._anchor_buffers: Dict[int, List[Tuple[float, float]]] = {}
        # Lưu anchor (bottom-center) đã làm mịn ở frame trước đó để kiểm tra giao cắt.
        self._last_smoothed_anchors: Dict[int, Tuple[float, float]] = {}
        
        # Thêm bộ đệm cho tâm (center) và đỉnh (top-center) của xe lớn (car, truck, bus) làm fallback
        self._center_buffers: Dict[int, List[Tuple[float, float]]] = {}
        self._last_smoothed_centers: Dict[int, Tuple[float, float]] = {}
        self._top_buffers: Dict[int, List[Tuple[float, float]]] = {}
        self._last_smoothed_tops: Dict[int, Tuple[float, float]] = {}
        
        # Lưu "side" theo từng (stable_id, line_idx) để xử lý điểm nằm đúng trên line.
        self._last_side: Dict[tuple[int, int], int] = {}
        # Chống đếm trùng: (stable_id, line_idx, direction) đã được cộng rồi.
        self._counted = set()  # (stable_id, line_idx, direction)
        # Mặc định cho phép đếm tất cả phương tiện chính, tránh lỗi filter từ Web UI
        self._allowed_names = {"motorcycle", "car", "truck", "bus"}
        self._frame_id = 0
        # Chống đếm 2 lần khi xe nháy/đổi ID lúc qua line: (x, y, frame_id, class_name)
        self._recent_positions: List[Tuple[float, float, int, str]] = []
        # Danh sách sự kiện đếm mới — FrameProcessor sẽ đọc và clear sau mỗi frame.
        self.pending_events: List[CountEvent] = []

    def process(self, tracks: List[TrackedObject]):
        self._frame_id += 1
        alive_stable_ids = set()
        for tr in tracks:
            sid = self._get_identity(tr)
            alive_stable_ids.add(sid)

        # Chỉ giữ counted entries của track còn sống
        self._counted = {k for k in self._counted if k[0] in alive_stable_ids}
        # Dọn dẹp bộ đệm của các track đã chết để tránh phình bộ nhớ
        self._anchor_buffers = {k: v for k, v in self._anchor_buffers.items() if k in alive_stable_ids}
        self._center_buffers = {k: v for k, v in self._center_buffers.items() if k in alive_stable_ids}
        self._top_buffers = {k: v for k, v in self._top_buffers.items() if k in alive_stable_ids}
        self._last_smoothed_anchors = {k: v for k, v in self._last_smoothed_anchors.items() if k in alive_stable_ids}
        self._last_smoothed_centers = {k: v for k, v in self._last_smoothed_centers.items() if k in alive_stable_ids}
        self._last_smoothed_tops = {k: v for k, v in self._last_smoothed_tops.items() if k in alive_stable_ids}
        
        # Xóa vị trí cũ (giữ ~45 frame)
        cutoff = self._frame_id - 45
        self._recent_positions = [(x, y, f, c) for x, y, f, c in self._recent_positions if f > cutoff]

        for tr in tracks:
            # Lọc theo các loại xe hợp lệ
            if tr.class_name not in self._allowed_names:
                continue
            # Ngưỡng tin cậy đếm: đặt 0.10 để không bị sót xe do độ tự tin nhận diện của YOLO
            # bị dao động giảm tạm thời đúng tại khung hình giao cắt.
            min_conf = 0.10
            if tr.confidence < min_conf:
                continue

            # Dùng stable_id làm key chính — ổn định qua các lần Re-ID
            identity = self._get_identity(tr)
            
            # 1. Quỹ đạo Bottom-Center (mặc định)
            raw_anchor = tr.last_anchor()
            bbox_w = tr.bbox[2] - tr.bbox[0]
            bbox_h = tr.bbox[3] - tr.bbox[1]
            cx, cy = raw_anchor
            
            if identity not in self._anchor_buffers:
                self._anchor_buffers[identity] = []
            self._anchor_buffers[identity].append(raw_anchor)
            
            _MA_WINDOW = 3
            if len(self._anchor_buffers[identity]) > _MA_WINDOW:
                self._anchor_buffers[identity] = self._anchor_buffers[identity][-_MA_WINDOW:]

            buf = self._anchor_buffers[identity]
            cx = sum(p[0] for p in buf) / len(buf)
            cy = sum(p[1] for p in buf) / len(buf)
            current = (cx, cy)
            
            # 2. Quỹ đạo Center (cho xe lớn làm fallback nếu khi xuất hiện bottom-center đã vượt quá vạch)
            raw_center = ((tr.bbox[0] + tr.bbox[2]) / 2.0, (tr.bbox[1] + tr.bbox[3]) / 2.0)
            if identity not in self._center_buffers:
                self._center_buffers[identity] = []
            self._center_buffers[identity].append(raw_center)
            
            if len(self._center_buffers[identity]) > _MA_WINDOW:
                self._center_buffers[identity] = self._center_buffers[identity][-_MA_WINDOW:]
                
            c_buf = self._center_buffers[identity]
            ccx = sum(p[0] for p in c_buf) / len(c_buf)
            ccy = sum(p[1] for p in c_buf) / len(c_buf)
            current_center = (ccx, ccy)

            # 3. Quỹ đạo Top-Center (cho xe lớn làm fallback thứ hai)
            raw_top = ((tr.bbox[0] + tr.bbox[2]) / 2.0, tr.bbox[1])
            if identity not in self._top_buffers:
                self._top_buffers[identity] = []
            self._top_buffers[identity].append(raw_top)
            
            if len(self._top_buffers[identity]) > _MA_WINDOW:
                self._top_buffers[identity] = self._top_buffers[identity][-_MA_WINDOW:]
                
            t_buf = self._top_buffers[identity]
            tcx = sum(p[0] for p in t_buf) / len(t_buf)
            tcy = sum(p[1] for p in t_buf) / len(t_buf)
            current_top = (tcx, tcy)
            
            prev = self._last_smoothed_anchors.get(identity)
            prev_center = self._last_smoothed_centers.get(identity)
            prev_top = self._last_smoothed_tops.get(identity)
            
            if prev is not None:
                for idx, (p1, p2) in enumerate(self.lines):
                    direction_allowed = (
                        self.line_directions[idx] if idx < len(self.line_directions) else "both"
                    )
                    
                    # Thử kiểm tra giao cắt bằng bottom-center trước
                    crossed, cross_dir = self._crossing(prev, current, p1, p2, identity, idx)
                    
                    # Nếu là xe lớn và bottom-center không giao cắt, thử kiểm tra bằng center làm fallback
                    if (not crossed or cross_dir is None) and tr.class_name in {"car", "truck", "bus"} and prev_center is not None:
                        crossed, cross_dir = self._crossing(prev_center, current_center, p1, p2, identity, idx)

                    # Nếu vẫn không giao cắt, thử kiểm tra bằng top-center làm fallback thứ hai (chỉ cho xe lớn)
                    if (not crossed or cross_dir is None) and tr.class_name in {"car", "truck", "bus"} and prev_top is not None:
                        crossed, cross_dir = self._crossing(prev_top, current_top, p1, p2, identity, idx)
                        
                    if not crossed or cross_dir is None:
                        continue

                    if direction_allowed not in {"both", cross_dir}:
                        continue

                    key = (identity, idx, cross_dir)
                    if key in self._counted:
                        continue

                    # Tính toán bán kính debounce thông minh chống đếm trùng do nhảy ID ngay tại vạch
                    bbox_diag = (bbox_w**2 + bbox_h**2) ** 0.5
                    # Tăng mạnh khoảng cách (tối thiểu 60px) và thời gian (12 frame ~ 0.8s) để chặn đứng mọi hành vi đếm trùng
                    debounce_radius = max(60.0, bbox_diag * 0.35)
                    debounce_frames = 12

                    skip = False
                    for rx, ry, rf, r_class in self._recent_positions:
                        if r_class == tr.class_name:
                            # Đảm bảo dùng cx, cy của điểm đáy để debounce nhất quán
                            if (self._frame_id - rf) <= debounce_frames and math.hypot(cx - rx, cy - ry) < debounce_radius:
                                skip = True
                                break
                    
                    if not skip:
                        self.stats.increment(tr.class_name)
                        self.stats.increment_direction(tr.class_name, cross_dir)
                        self._counted.add(key)
                        self._recent_positions.append((cx, cy, self._frame_id, tr.class_name))
                        # Emit event để persistence layer ghi vào DB.
                        self.pending_events.append(CountEvent(
                            track_id=tr.track_id,
                            class_name=tr.class_name,
                            confidence=tr.confidence,
                            direction=cross_dir,
                            line_index=idx,
                            anchor_x=cx,
                            anchor_y=cy,
                        ))
            self._last_smoothed_anchors[identity] = current
            self._last_smoothed_centers[identity] = current_center
            self._last_smoothed_tops[identity] = current_top
        return self.stats

    @staticmethod
    def _get_identity(tr: TrackedObject) -> int:
        """Lấy identity ổn định nhất có thể: stable_id > track_id.
        
        stable_id được gán bởi Re-ID tracker, giữ nguyên khi ByteTrack đổi track_id.
        Nếu không có stable_id (tracker cũ), fallback về track_id.
        """
        if tr.stable_id is not None:
            return tr.stable_id
        return tr.track_id

    def reset(self) -> None:
        super().reset()
        self._last_smoothed_anchors = {}
        self._last_smoothed_centers = {}
        self._last_smoothed_tops = {}
        self._anchor_buffers = {}
        self._center_buffers = {}
        self._top_buffers = {}
        self._last_side = {}
        self._counted = set()
        self._recent_positions = []
        self.pending_events = []

    def _crossing(
        self,
        prev: Tuple[float, float],
        cur: Tuple[float, float],
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        identity: int,
        line_idx: int,
    ) -> tuple[bool, str | None]:
        """
        Determine if the anchor segment prev->cur crosses the actual counting
        line segment p1->p2, and infer direction as 'p1_to_p2' or 'p2_to_p1'.
        """

        def side(pt: Tuple[float, float]) -> int:
            # sign of cross((p2-p1),(pt-p1))
            x, y = pt
            x1, y1 = p1
            x2, y2 = p2
            v = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
            if abs(v) < 1e-6:
                return 0
            return 1 if v > 0 else -1

        s_prev = side(prev)
        s_cur = side(cur)

        key = (identity, line_idx)
        if s_prev == 0:
            s_prev = self._last_side.get(key, 0)
        if s_cur != 0:
            self._last_side[key] = s_cur

        # Reject motion that never intersects the finite line segment.
        if not line_intersection(prev, cur, p1, p2):
            return False, None

        # Need a side change to infer direction reliably.
        if s_prev == 0 and s_cur == 0:
            return False, None
        if s_prev == 0:
            s_prev = -s_cur
        if s_cur == 0:
            s_cur = -s_prev
        if (s_prev * s_cur) >= 0:
            return False, None

        cross_dir = "p1_to_p2" if s_prev < s_cur else "p2_to_p1"
        return True, cross_dir
