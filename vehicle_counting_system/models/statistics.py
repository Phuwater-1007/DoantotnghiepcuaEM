# ===== file: models/statistics.py =====
"""Container for aggregated counting statistics.
Holds total counts and per-class breakdown.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Statistics:
    total: int = 0
    per_class: Dict[str, int] = field(default_factory=dict)

    def increment(self, class_name: str, amount: int = 1):
        """Increase counters when a vehicle is counted."""
        self.total += amount
        self.per_class[class_name] = self.per_class.get(class_name, 0) + amount

    def reset(self):
        """Clear statistics (e.g., new video)."""
        self.total = 0
        self.per_class.clear()
