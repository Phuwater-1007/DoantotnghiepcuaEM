"""Orchestrate counting and LPR processors without sharing mutable state."""

from __future__ import annotations

import copy

from vehicle_counting_system.core.frame_processor import FrameProcessor
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker


class _DetectorView:
    """Per-pipeline view of one immutable detector result for the current frame."""
    def __init__(self):
        self._detections = []

    def prime(self, detections):
        self._detections = copy.deepcopy(detections)

    def detect(self, frame):
        return self._detections


class IndependentAnalysisPipelines:
    def __init__(
        self,
        *,
        detector,
        counting_lines_path=None,
        frame_size=None,
        counting_persistence_callback=None,
        lpr_persistence_callback=None,
        analysis_mode="line",
        min_track_frames=5,
        enable_counting=True,
        enable_lpr=True,
        session_id=0,
        tracker_factory=ByteTrackTracker,
    ):
        if not enable_counting and not enable_lpr:
            raise ValueError("At least one analysis pipeline must be enabled.")
        common = dict(
            counting_lines_path=counting_lines_path,
            frame_size=frame_size,
            analysis_mode=analysis_mode,
            min_track_frames=min_track_frames,
        )
        self._detector = detector
        self._counting_detector = _DetectorView() if enable_counting else None
        self._lpr_detector = _DetectorView() if enable_lpr else None
        self.counting = FrameProcessor(
            detector=self._counting_detector,
            tracker=tracker_factory(),
            counting_persistence_callback=counting_persistence_callback,
            enable_counting=True,
            enable_lpr=False,
            **common,
        ) if enable_counting else None
        self.lpr = FrameProcessor(
            detector=self._lpr_detector,
            tracker=tracker_factory(),
            lpr_persistence_callback=lpr_persistence_callback,
            enable_counting=False,
            enable_lpr=True,
            **common,
        ) if enable_lpr else None
        for processor in (self.counting, self.lpr):
            if processor is not None:
                processor.session_id = session_id

    @property
    def last_stats(self):
        return self.counting.last_stats if self.counting is not None else None

    def process(self, frame):
        detections = self._detector.detect(frame)
        if self._counting_detector is not None:
            self._counting_detector.prime(detections)
        if self._lpr_detector is not None:
            self._lpr_detector.prime(detections)
        counting_frame = self.counting.process(frame.copy()) if self.counting is not None else None
        lpr_frame = self.lpr.process(frame.copy()) if self.lpr is not None else None
        return counting_frame if counting_frame is not None else lpr_frame

    def reset(self):
        for processor in (self.counting, self.lpr):
            if processor is not None:
                processor.reset()

    def set_active_classes(self, classes):
        for processor in (self.counting, self.lpr):
            if processor is not None:
                processor.set_active_classes(classes)

    def close(self):
        for processor in (self.counting, self.lpr):
            if processor is not None:
                processor.close()
