# ===== file: counters/line_counter.py =====
"""Count objects crossing configured lines using bottom-center trajectory.

Cải tiến so với phiên bản gốc:
1. TTL-based _counted dict  — không xóa khi track mất, tránh đếm trùng do ID tái sử dụng.
2. MIN_TRACK_FRAMES         — chỉ đếm khi track đã tồn tại ≥ N frame (lọc noise ngắn).
3. MIN_MOVEMENT_PX          — jitter filter lớn hơn (6px thay vì 3px).
4. Larger spatial debounce  — bán kính 80px, cửa sổ 45 frame (thay vì 40px / 20 frame).
5. Direction consistency     — kiểm tra 3 anchor liên tiếp cùng tiến về line trước khi đếm.
"""

import math
from typing import Dict, List, Tuple

from vehicle_counting_system.counters.base_counter import BaseCounter
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.utils.math_utils import line_intersection


class LineCounter(BaseCounter):
    # ── Tuning constants ──────────────────────────────────────────────────────
    # Minimum frames a track must exist before it can trigger a count.
    # Filters short-lived noise detections that appear right at the line.
    _MIN_TRACK_FRAMES: int = 3

    # Minimum anchor displacement (px) per frame — suppresses stationary jitter.
    _MIN_MOVEMENT_PX: float = 6.0

    # Spatial debounce: ignore a new crossing if another one occurred within
    # this radius (px) and time window (frames). Handles ID-swap near the line.
    _DEBOUNCE_RADIUS_PX: float = 80.0
    _DEBOUNCE_WINDOW_FRAMES: int = 45

    # How long (frames) to keep a counted record before it expires.
    # 90 frames ≈ 3 s @ 30 fps — prevents double-count from brief ID loss.
    _COUNTED_TTL_FRAMES: int = 90

    # How many past anchors to check for consistent approach direction.
    _DIRECTION_HISTORY: int = 3
    # ─────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        lines: List[Tuple[Tuple[int, int], Tuple[int, int]]],
        *,
        line_directions: List[str] | None = None,
    ):
        super().__init__()
        self.lines = lines
        self.line_directions = line_directions or ["both"] * len(lines)

        # Lưu anchor (bottom-center) frame trước đó để kiểm tra giao cắt.
        self._last_anchors: Dict[int, Tuple[float, float]] = {}

        # Lưu "side" theo từng (track_id, line_idx).
        self._last_side: Dict[Tuple[int, int], int] = {}

        # TTL-based counted dict: key=(track_id, line_idx, dir), value=frame_id
        # Không xóa ngay khi track biến mất — expire sau _COUNTED_TTL_FRAMES.
        self._counted: Dict[Tuple, int] = {}

        self._allowed_names = set(settings.allowed_class_names)
        self._frame_id = 0

        # Spatial debounce: danh sách (x, y, frame_id) các vị trí vừa đếm.
        self._recent_positions: List[Tuple[float, float, int]] = []

    # ── Main processing loop ──────────────────────────────────────────────────

    def process(self, tracks: List[TrackedObject]):
        self._frame_id += 1

        # 1. Expire counted records (TTL-based — không phụ thuộc alive_ids).
        cutoff_counted = self._frame_id - self._COUNTED_TTL_FRAMES
        self._counted = {k: v for k, v in self._counted.items() if v > cutoff_counted}

        # 2. Expire spatial debounce positions.
        cutoff_pos = self._frame_id - self._DEBOUNCE_WINDOW_FRAMES
        self._recent_positions = [
            (x, y, f) for x, y, f in self._recent_positions if f > cutoff_pos
        ]

        for tr in tracks:
            # ── Class & confidence filter ──────────────────────────────────
            if self._allowed_names and tr.class_name not in self._allowed_names:
                continue
            if tr.confidence < 0.4:
                continue

            # ── Minimum track age (NEW) ────────────────────────────────────
            # Track phải có ít nhất _MIN_TRACK_FRAMES điểm lịch sử.
            # Loại bỏ detection nhiễu ngắn ngay gần đường đếm.
            if len(tr.history) < self._MIN_TRACK_FRAMES:
                continue

            track_id = tr.track_id
            current = tr.last_anchor()
            prev = self._last_anchors.get(track_id)

            if prev is not None:
                for idx, (p1, p2) in enumerate(self.lines):
                    direction_allowed = (
                        self.line_directions[idx]
                        if idx < len(self.line_directions)
                        else "both"
                    )

                    crossed, cross_dir = self._crossing(prev, current, p1, p2, track_id, idx)
                    if not crossed or cross_dir is None:
                        continue

                    # ── Jitter filter (improved: 6px) ──────────────────────
                    if math.hypot(current[0] - prev[0], current[1] - prev[1]) < self._MIN_MOVEMENT_PX:
                        continue

                    # ── Direction filter ───────────────────────────────────
                    if direction_allowed not in {"both", cross_dir}:
                        continue

                    # ── Direction consistency check (NEW) ──────────────────
                    # Kiểm tra N anchor gần nhất đều tiếp cận line từ cùng phía.
                    # Tránh đếm khi xe dao động qua lại gần line.
                    if not self._consistent_approach(tr.history, p1, p2, cross_dir):
                        continue

                    # ── TTL-based duplicate check ──────────────────────────
                    key = (track_id, idx, cross_dir)
                    if key in self._counted:
                        continue

                    # ── Spatial debounce (improved: 80px / 45 frames) ──────
                    cx, cy = current
                    skip = any(
                        math.hypot(cx - rx, cy - ry) < self._DEBOUNCE_RADIUS_PX
                        for rx, ry, _ in self._recent_positions
                    )
                    if skip:
                        continue

                    # ── Count! ─────────────────────────────────────────────
                    self.stats.increment(tr.class_name)
                    self._counted[key] = self._frame_id
                    self._recent_positions.append((cx, cy, self._frame_id))

            self._last_anchors[track_id] = current

        return self.stats

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        super().reset()
        self._last_anchors = {}
        self._last_side = {}
        self._counted = {}
        self._recent_positions = []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _crossing(
        self,
        prev: Tuple[float, float],
        cur: Tuple[float, float],
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        track_id: int,
        line_idx: int,
    ) -> tuple[bool, str | None]:
        """Determine if the anchor segment prev→cur crosses line segment p1→p2."""

        def side(pt: Tuple[float, float]) -> int:
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

        if not line_intersection(prev, cur, p1, p2):
            return False, None

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

    def _consistent_approach(
        self,
        history: List[Tuple[float, float]],
        p1: Tuple[int, int],
        p2: Tuple[int, int],
        expected_dir: str,
    ) -> bool:
        """Return True nếu các anchor gần nhất nhất quán tiếp cận line từ cùng 1 phía.

        Cần ít nhất _DIRECTION_HISTORY điểm. Nếu không đủ history, cho phép đếm.
        """
        n = self._DIRECTION_HISTORY
        if len(history) < n + 1:
            # Không đủ dữ liệu — cho phép (đã có MIN_TRACK_FRAMES kiểm tra trước)
            return True

        def side(pt: Tuple[float, float]) -> int:
            x, y = pt
            x1, y1 = p1
            x2, y2 = p2
            v = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
            return 1 if v > 0 else -1 if v < 0 else 0

        # Lấy N+1 anchor cuối (trước khi crossing xảy ra)
        recent = history[-(n + 1):-1]  # bỏ điểm cuối cùng (đã qua line)
        expected_side = -1 if expected_dir == "p1_to_p2" else 1

        sides = [side(pt) for pt in recent]
        non_zero = [s for s in sides if s != 0]
        if not non_zero:
            return True  # tất cả nằm trên line — không đủ thông tin

        # Nếu đa số điểm ở đúng phía tiếp cận → hợp lệ
        matching = sum(1 for s in non_zero if s == expected_side)
        return matching >= len(non_zero) // 2 + 1
