# ===== file: trackers/bytetrack_tracker.py =====
from __future__ import annotations

from typing import Dict, List

import numpy as np
import supervision as sv

from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.models.detection import Detection
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.trackers.base_tracker import BaseTracker


class ByteTrackTracker(BaseTracker):
    """
    ByteTrack tracker wrapper using `supervision` implementation.

    Goals for graduation demo:
    - Stable IDs under occlusion / dense traffic (better than IoU-only matching)
    - Lightweight enough for RTX 3050
    - Minimal integration changes (keep detect -> track -> count pipeline)
    """

    def __init__(self):
        self._init_state()

    def _init_state(self) -> None:
        self._frame_idx = 0
        self._next_display_id = 1
        self._bt = sv.ByteTrack(
            track_activation_threshold=settings.bytetrack_activation_threshold,
            lost_track_buffer=settings.bytetrack_lost_buffer,
            minimum_matching_threshold=settings.bytetrack_matching_threshold,
            # Use nominal frame_rate; counting uses geometric crossing so exact fps not critical.
            frame_rate=30,
            minimum_consecutive_frames=settings.bytetrack_min_consecutive,
        )
        self._tracks = {}
        self._last_seen = {}

    def reset(self) -> None:
        # supervision ByteTrack has its own internal state; easiest & safest is recreate it.
        self._init_state()

    def update(self, detections: List[Detection]) -> List[TrackedObject]:
        self._frame_idx += 1

        if not detections:
            # Prune stale tracks (avoid memory growth).
            self._prune_stale()
            return []

        xyxy = np.array([d.bbox for d in detections], dtype=np.float32)
        conf = np.array([d.confidence for d in detections], dtype=np.float32)
        cls = np.array([d.class_id for d in detections], dtype=np.int32)
        # Best-effort map from class_id to class_name from detector output.
        cls_name_map: Dict[int, str] = {}
        for d in detections:
            cls_name_map.setdefault(int(d.class_id), d.class_name)

        dets = sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls)
        tracked = self._bt.update_with_detections(dets)

        out: List[TrackedObject] = []
        if tracked.tracker_id is None or len(tracked) == 0:
            self._prune_stale()
            return out

        # Map back to our TrackedObject (keep anchor history).
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            bbox = tuple(map(float, tracked.xyxy[i]))
            confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            class_id = int(tracked.class_id[i]) if tracked.class_id is not None else -1

            class_name = cls_name_map.get(class_id, str(class_id))

            if tid in self._tracks:
                obj = self._tracks[tid]
                obj.update(bbox, class_id=class_id, class_name=class_name, confidence=confidence)
            else:
                display_id = self._next_display_id
                self._next_display_id += 1
                obj = TrackedObject(
                    track_id=tid,
                    class_id=class_id,
                    class_name=class_name,
                    bbox=bbox,
                    confidence=confidence,
                    history=[],
                    display_id=display_id,
                )
                obj.update(bbox, class_id=class_id, class_name=class_name, confidence=confidence)
                self._tracks[tid] = obj

            self._last_seen[tid] = self._frame_idx
            out.append(obj)

        self._prune_stale()
        return out

    def _prune_stale(self) -> None:
        # Remove tracks not seen longer than lost buffer (with small margin).
        stale_after = settings.bytetrack_lost_buffer + 5
        stale_ids = [
            tid for tid, last in self._last_seen.items() if (self._frame_idx - last) > stale_after
        ]
        for tid in stale_ids:
            self._last_seen.pop(tid, None)
            self._tracks.pop(tid, None)