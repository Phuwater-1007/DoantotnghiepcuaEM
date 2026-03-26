# ===== file: detectors/base_detector.py =====
"""Abstract base class for detectors.
Each concrete detector must implement `detect(frame)` returning a list of
`models.detection.Detection` objects.
"""

from abc import ABC, abstractmethod
from typing import List
from vehicle_counting_system.models.detection import Detection


class BaseDetector(ABC):

    @abstractmethod
    def detect(self, frame) -> List[Detection]:
        """Run detection on a single frame and return detections."""
        pass
