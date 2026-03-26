# ===== file: core/state_manager.py =====
"""Simple state container for runtime information (could be expanded later)."""
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class StateManager:
    state: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any):
        self.state[key] = value

    def get(self, key: str, default=None):
        return self.state.get(key, default)
