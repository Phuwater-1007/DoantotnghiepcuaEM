from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class PresenceSnapshot:
    active_tabs: int
    last_seen_ts: float


class ClientPresence:
    """Tracks whether any browser tab is still alive (heartbeat-based)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_tabs = 0
        self._last_seen_ts = 0.0

    def heartbeat(self) -> PresenceSnapshot:
        now = time.time()
        with self._lock:
            # We only need to know "someone is alive".
            self._active_tabs = 1
            self._last_seen_ts = now
            return PresenceSnapshot(active_tabs=self._active_tabs, last_seen_ts=self._last_seen_ts)

    def tab_closed(self) -> PresenceSnapshot:
        now = time.time()
        with self._lock:
            # Treat as "no active tabs" but still record when we last heard from client.
            self._active_tabs = 0
            self._last_seen_ts = now
            return PresenceSnapshot(active_tabs=self._active_tabs, last_seen_ts=self._last_seen_ts)

    def snapshot(self) -> PresenceSnapshot:
        with self._lock:
            return PresenceSnapshot(active_tabs=self._active_tabs, last_seen_ts=self._last_seen_ts)

