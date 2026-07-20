"""Count unique vehicle identities observed across the whole video."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

from vehicle_counting_system.counters.base_counter import BaseCounter
from vehicle_counting_system.models.tracked_object import TrackedObject


VEHICLE_CLASSES = ("motorcycle", "car", "bus", "truck")


@dataclass
class _TrackEvidence:
    frames_seen: int = 0
    class_votes: Counter = field(default_factory=Counter)


class PanoramaCounter(BaseCounter):
    """Count each stable Track ID once after it survives enough frames."""

    def __init__(self, min_track_frames: int = 5):
        super().__init__()
        self.min_track_frames = max(1, int(min_track_frames))
        self._allowed_names = set(VEHICLE_CLASSES)
        self._evidence: Dict[int, _TrackEvidence] = {}
        self._confirmed: Dict[int, str] = {}

    @staticmethod
    def _identity(track: TrackedObject) -> int:
        return track.stable_id if track.stable_id is not None else track.track_id

    @staticmethod
    def _winning_class(votes: Counter) -> str | None:
        valid = [(count, name) for name, count in votes.items() if name in VEHICLE_CLASSES]
        if not valid:
            return None
        order = {name: -index for index, name in enumerate(VEHICLE_CLASSES)}
        return max(valid, key=lambda item: (item[0], order[item[1]]))[1]

    def process(self, tracks: List[TrackedObject]):
        seen_this_frame: set[int] = set()
        for track in tracks:
            identity = self._identity(track)
            if identity in seen_this_frame or track.class_name not in self._allowed_names:
                continue
            seen_this_frame.add(identity)
            evidence = self._evidence.setdefault(identity, _TrackEvidence())
            evidence.frames_seen += 1
            evidence.class_votes[track.class_name] += 1
            if evidence.frames_seen < self.min_track_frames:
                continue
            vehicle_class = self._winning_class(evidence.class_votes)
            if vehicle_class is None:
                continue
            previous = self._confirmed.get(identity)
            if previous == vehicle_class:
                continue
            if previous is not None:
                self.stats.per_class[previous] -= 1
            else:
                self.stats.total += 1
            self.stats.per_class[vehicle_class] = self.stats.per_class.get(vehicle_class, 0) + 1
            self._confirmed[identity] = vehicle_class
        for name in VEHICLE_CLASSES:
            self.stats.per_class.setdefault(name, 0)
        return self.stats

    def reset(self) -> None:
        super().reset()
        self._evidence.clear()
        self._confirmed.clear()
