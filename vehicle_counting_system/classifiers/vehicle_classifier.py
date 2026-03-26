from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Deque, Dict, List

from vehicle_counting_system.classifiers.base_classifier import BaseClassifier
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.configs.settings import settings


@dataclass
class _Vote:
    cls: str
    conf: float


class VehicleClassifier(BaseClassifier):
    """
    Temporal class smoothing per track_id.

    Why: detector class can flicker frame-to-frame under occlusion / small objects,
    causing unstable stats and wrong class-at-counting-time.
    """

    def classify(self, tracks: List[TrackedObject]) -> List[TrackedObject]:
        if not tracks:
            return tracks

        for tr in tracks:
            tid = tr.track_id
            buf = self._buffers.get(tid)
            if buf is None:
                buf = deque(maxlen=max(3, settings.class_smoothing_window))
                self._buffers[tid] = buf
            buf.append(_Vote(tr.class_name, float(tr.confidence)))

            smoothed = self._smooth(buf)
            if smoothed is not None:
                tr.class_name = smoothed
        self._prune_missing({t.track_id for t in tracks})
        return tracks

    def __init__(self):
        self._buffers: Dict[int, Deque[_Vote]] = {}
        self._last_seen: Dict[int, int] = {}
        self._frame_idx = 0

    def reset(self) -> None:
        self._buffers.clear()
        self._last_seen.clear()
        self._frame_idx = 0

    def _smooth(self, buf: Deque[_Vote]) -> str | None:
        if len(buf) < max(1, settings.class_smoothing_min_votes):
            return None

        # Weighted majority vote by confidence, fallback to unweighted counts.
        weighted: Dict[str, float] = {}
        for v in buf:
            weighted[v.cls] = weighted.get(v.cls, 0.0) + max(0.0, v.conf)
        if weighted:
            return max(weighted.items(), key=lambda kv: kv[1])[0]
        return Counter([v.cls for v in buf]).most_common(1)[0][0]

    def _prune_missing(self, alive_ids: set[int]) -> None:
        # Keep buffers only for currently alive IDs to avoid growth.
        drop = [tid for tid in self._buffers.keys() if tid not in alive_ids]
        for tid in drop:
            self._buffers.pop(tid, None)

