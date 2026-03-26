from __future__ import annotations

from typing import List

from vehicle_counting_system.counters.base_counter import BaseCounter
from vehicle_counting_system.models.tracked_object import TrackedObject


class DirectionCounter(BaseCounter):
    """
    Placeholder for direction-aware counting (e.g. up/down).
    """

    def process(self, tracks: List[TrackedObject]):
        return self.stats

