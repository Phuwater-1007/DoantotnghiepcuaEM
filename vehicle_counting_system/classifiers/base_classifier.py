from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from vehicle_counting_system.models.tracked_object import TrackedObject


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, tracks: List[TrackedObject]) -> List[TrackedObject]:
        """Optionally enrich tracked objects with finer-grained labels."""
        raise NotImplementedError

