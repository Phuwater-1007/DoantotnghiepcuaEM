# ===== file: models/tracked_object.py =====
"""Represents an object being tracked across frames.
Holds an id, last known bbox, class information and trajectory of centers.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from vehicle_counting_system.utils.math_utils import get_bbox_bottom_center


# Max history points to avoid unbounded memory growth (line crossing needs last 2).
_HISTORY_CAP = 128


@dataclass
class TrackedObject:
    track_id: int
    class_id: int
    class_name: str
    bbox: Tuple[float, float, float, float]
    confidence: float = 0.0
    # Trajectory of anchor points (bottom-center) for counting/ROI logic.
    history: List[Tuple[float, float]] = field(default_factory=list)
    # Display ID: số tuần tự 1,2,3... để hiển thị, ổn định hơn track_id từ ByteTrack.
    display_id: int | None = None

    def update(
        self,
        bbox: Tuple[float, float, float, float],
        *,
        class_id: int | None = None,
        class_name: str | None = None,
        confidence: float | None = None,
    ):
        """Update bbox (+ optional metadata) and append new anchor to history."""
        self.bbox = bbox
        if class_id is not None:
            self.class_id = class_id
        if class_name is not None:
            self.class_name = class_name
        if confidence is not None:
            self.confidence = confidence
        anchor = get_bbox_bottom_center(bbox)
        self.history.append(anchor)
        if len(self.history) > _HISTORY_CAP:
            self.history = self.history[-_HISTORY_CAP:]

    def last_anchor(self) -> Tuple[float, float]:
        """Return the most recent bottom-center anchor; used for counting logic."""
        if self.history:
            return self.history[-1]
        return get_bbox_bottom_center(self.bbox)

    # Backwards-compat: old code may call last_center()
    def last_center(self) -> Tuple[float, float]:
        return self.last_anchor()

    def get_display_id(self) -> int:
        """ID dùng để hiển thị (tuần tự, ổn định)."""
        return self.display_id if self.display_id is not None else self.track_id
