# ===== file: models/statistics.py =====
"""Container for aggregated counting statistics.
Holds total counts, per-class breakdown, and per-direction breakdown.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Statistics:
    total: int = 0
    per_class: Dict[str, int] = field(default_factory=dict)

    # Đếm theo chiều: key = "p1_to_p2" (Đi) | "p2_to_p1" (Về)
    # Mỗi chiều lưu {total: int, per_class: Dict[str, int]}
    per_direction: Dict[str, Dict] = field(default_factory=lambda: {
        "p1_to_p2": {"total": 0, "per_class": {}},
        "p2_to_p1": {"total": 0, "per_class": {}},
    })

    def increment(self, class_name: str, amount: int = 1):
        """Increase counters when a vehicle is counted."""
        self.total += amount
        self.per_class[class_name] = self.per_class.get(class_name, 0) + amount

    def increment_direction(self, class_name: str, direction: str, amount: int = 1):
        """Increase directional counters (Đi = p1_to_p2, Về = p2_to_p1)."""
        bucket = self.per_direction.setdefault(direction, {"total": 0, "per_class": {}})
        bucket["total"] += amount
        bucket["per_class"][class_name] = bucket["per_class"].get(class_name, 0) + amount

    def reset(self):
        """Clear statistics (e.g., new video)."""
        self.total = 0
        self.per_class.clear()
        self.per_direction = {
            "p1_to_p2": {"total": 0, "per_class": {}},
            "p2_to_p1": {"total": 0, "per_class": {}},
        }
