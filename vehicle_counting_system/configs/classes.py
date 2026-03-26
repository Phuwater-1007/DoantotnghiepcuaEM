"""
Class mappings and utilities.

Keep this small at first; you can later replace it with a dataset-specific
mapping (e.g. COCO vehicle classes only, or your custom-trained YOLO classes).
"""

from __future__ import annotations

# Default: use YOLO/COCO names as returned by the model.
# If you want to filter only vehicle-like classes, put them here.
DEFAULT_VEHICLE_CLASS_NAMES = {
    "car",
    "motorcycle",
    "bus",
    "truck",
    "bicycle",
}

