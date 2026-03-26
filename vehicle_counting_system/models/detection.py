# ===== file: models/detection.py =====
"""Data class representing a detection output from the detector.
Contains bounding box, confidence, class id, and a computed center point.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Detection:
    # top-left corner (x1, y1), bottom-right (x2, y2)
    bbox: Tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str

    def center(self) -> Tuple[float, float]:
        """Compute center coordinates of the bbox."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
