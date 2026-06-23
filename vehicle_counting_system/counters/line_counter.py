# ===== file: counters/line_counter.py =====
"""Count objects crossing configured lines using bottom-center trajectory."""

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
        # Bộ đệm lưu trữ quỹ đạo thô để làm mịn: track_id -> List[Tuple[float, float]]
        self._anchor_buffers: Dict[int, List[Tuple[float, float]]] = {}
        # Lưu anchor (bottom-center) đã làm mịn ở frame trước đó để kiểm tra giao cắt.
        self._last_smoothed_anchors: Dict[int, Tuple[float, float]] = {}
        self._last_anchors = {}  # Backward-compat
        # Lưu "side" theo từng (track_id, line_idx) để xử lý điểm nằm đúng trên line.
        self._last_side: Dict[tuple[int, int], int] = {}
        # Chống đếm trùng: (track_id, line_idx) đã được cộng rồi.
        self._counted = set()  # (track_id, line_idx, direction)
        self._allowed_names = set(settings.allowed_class_names)
        self._frame_id = 0
        # Chống đếm 2 lần khi xe nháy/đổi ID lúc qua line: (x, y, frame_id)
        self._recent_positions: List[Tuple[float, float, int]] = []
        # Danh sách sự kiện đếm mới — FrameProcessor sẽ đọc và clear sau mỗi frame.
        self.pending_events: List[CountEvent] = []

    def process(self, tracks: List[TrackedObject]):
        self._frame_id += 1
        alive_ids = {tr.track_id for tr in tracks}
        self._counted = {k for k in self._counted if k[0] in alive_ids}
        # Dọn dẹp bộ đệm của các track đã chết để tránh phình bộ nhớ
        self._anchor_buffers = {k: v for k, v in self._anchor_buffers.items() if k in alive_ids}
        self._last_smoothed_anchors = {k: v for k, v in self._last_smoothed_anchors.items() if k in alive_ids}
        
        # Xóa vị trí cũ (giữ ~45 frame)
        cutoff = self._frame_id - 45
        self._recent_positions = [(x, y, f) for x, y, f in self._recent_positions if f > cutoff]

        for tr in tracks:
            if self._allowed_names and tr.class_name not in self._allowed_names:
                continue
            if tr.confidence < 0.3:
                continue

            track_id = tr.track_id
            raw_anchor = tr.last_anchor()
            
            # Đẩy tọa độ thô vào bộ đệm rolling 5 frame
            if track_id not in self._anchor_buffers:
                self._anchor_buffers[track_id] = []
            self._anchor_buffers[track_id].append(raw_anchor)
            if len(self._anchor_buffers[track_id]) > 5:
                self._anchor_buffers[track_id].pop(0)

            # Tính tọa độ trung bình trượt làm mịn (Moving Average)
            buf = self._anchor_buffers[track_id]
            cx = sum(p[0] for p in buf) / len(buf)
            cy = sum(p[1] for p in buf) / len(buf)
            current = (cx, cy)

            prev = self._last_smoothed_anchors.get(track_id)
            if prev is not None:
                for idx, (p1, p2) in enumerate(self.lines):
                    direction_allowed = (
                        self.line_directions[idx] if idx < len(self.line_directions) else "both"
                    )
                    crossed, cross_dir = self._crossing(prev, current, p1, p2, track_id, idx)
                    if not crossed or cross_dir is None:
                        continue

                    # Bỏ qua jitter nhỏ (chỉ <3px) - tránh đếm nhầm khi anchor dao động trên line.
                    if math.hypot(current[0] - prev[0], current[1] - prev[1]) < 3:
                        continue

                    if direction_allowed not in {"both", cross_dir}:
                        continue

                    key = (track_id, idx, cross_dir)
                    if key in self._counted:
                        continue

                    # Spatial-Temporal Debounce nâng cao:
                    # Bỏ qua nếu có phương tiện cùng loại vừa được đếm ở vị trí gần đó trong vòng 30 frame gần nhất (chống lỗi đổi ID)
                    skip = False
                    for rx, ry, rf in self._recent_positions:
                        if (self._frame_id - rf) <= 30 and math.hypot(cx - rx, cy - ry) < 45:
                            skip = True
                            break
                    if not skip:
                        self.stats.increment(tr.class_name)
                        self.stats.increment_direction(tr.class_name, cross_dir)
                        self._counted.add(key)
                        self._recent_positions.append((cx, cy, self._frame_id))
                        # Emit event để persistence layer ghi vào DB.
                        self.pending_events.append(CountEvent(
                            track_id=track_id,
                            class_name=tr.class_name,
                            confidence=tr.confidence,
                            direction=cross_dir,
                            line_index=idx,
                            anchor_x=cx,
                            anchor_y=cy,
                        ))
            self._last_smoothed_anchors[track_id] = current
            self._last_anchors[track_id] = current
        return self.stats

    def reset(self) -> None:
        super().reset()
        self._last_anchors = {}
        self._last_smoothed_anchors = {}
        self._anchor_buffers = {}
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
        track_id: int,
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

        key = (track_id, line_idx)
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
