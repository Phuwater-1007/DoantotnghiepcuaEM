# ===== file: trackers/base_tracker.py =====
"""Abstract tracker interface. Trackers assign IDs to detections and
maintain object trajectories.
"""
from abc import ABC, abstractmethod
from typing import List
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.models.detection import Detection


class BaseTracker(ABC):

    @abstractmethod
    def update(self, detections: List[Detection]) -> List[TrackedObject]:
        """Given new detections, update tracking state and return tracked objects."""
        pass

    def reset(self) -> None:
        """Reset internal state so the tracker can be reused for a new video/run."""
        return None
