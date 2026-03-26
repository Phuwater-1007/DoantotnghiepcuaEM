from __future__ import annotations

from typing import List, Tuple

from vehicle_counting_system.counters.base_counter import BaseCounter
from vehicle_counting_system.models.tracked_object import TrackedObject


class ZoneCounter(BaseCounter):
    """
    Placeholder zone counter.

    A real implementation would count vehicles entering/exiting a polygon ROI.
    """

    def __init__(self, polygon: List[Tuple[int, int]]):
        super().__init__()
        self.polygon = polygon

    def process(self, tracks: List[TrackedObject]):
        return self.stats

