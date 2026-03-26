# ===== file: counters/base_counter.py =====
"""Abstract base class for counters. A counter consumes tracked objects and
may update statistics.
"""
from abc import ABC, abstractmethod
from typing import List
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.models.statistics import Statistics


class BaseCounter(ABC):
    def __init__(self):
        self.stats = Statistics()

    @abstractmethod
    def process(self, tracks: List[TrackedObject]):
        """Process a list of tracked objects for counting purposes."""
        pass

    def reset(self) -> None:
        """Reset internal state so the counter can be reused for a new video/run."""
        self.stats = Statistics()
