import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vehicle_counting_system.core.independent_pipelines import IndependentAnalysisPipelines
from vehicle_counting_system.core.frame_processor import FrameProcessor


class _FakeProcessor:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.session_id = 0
        self.last_stats = SimpleNamespace(total=3, per_class={"car": 3})
        self.process_calls = 0
        _FakeProcessor.instances.append(self)

    def process(self, frame):
        self.process_calls += 1
        frame[0, 0, 0] = 11 if self.kwargs["enable_counting"] else 22
        return frame

    def set_active_classes(self, classes):
        pass

    def reset(self):
        pass

    def close(self):
        pass


class _FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return []


class IndependentPipelineModeTests(unittest.TestCase):
    def setUp(self):
        _FakeProcessor.instances.clear()
        self.frame = np.zeros((2, 2, 3), dtype=np.uint8)

    def _make(self, counting, lpr):
        detector = _FakeDetector()
        with patch("vehicle_counting_system.core.independent_pipelines.FrameProcessor", _FakeProcessor), patch(
            "vehicle_counting_system.core.independent_pipelines.ByteTrackTracker", side_effect=lambda: object()
        ):
            return IndependentAnalysisPipelines(
                detector=detector, enable_counting=counting, enable_lpr=lpr, session_id=42
            )

    def test_counting_only_does_not_construct_lpr(self):
        pipelines = self._make(True, False)
        pipelines.process(self.frame)
        self.assertEqual(len(_FakeProcessor.instances), 1)
        self.assertTrue(_FakeProcessor.instances[0].kwargs["enable_counting"])
        self.assertFalse(_FakeProcessor.instances[0].kwargs["enable_lpr"])

    def test_lpr_only_does_not_construct_counter(self):
        pipelines = self._make(False, True)
        pipelines.process(self.frame)
        self.assertEqual(len(_FakeProcessor.instances), 1)
        self.assertFalse(_FakeProcessor.instances[0].kwargs["enable_counting"])
        self.assertTrue(_FakeProcessor.instances[0].kwargs["enable_lpr"])
        self.assertIsNone(pipelines.last_stats)

    def test_combined_uses_two_processors_and_independent_frame_copies(self):
        pipelines = self._make(True, True)
        output = pipelines.process(self.frame)
        self.assertEqual(len(_FakeProcessor.instances), 2)
        self.assertIsNot(_FakeProcessor.instances[0].kwargs["tracker"], _FakeProcessor.instances[1].kwargs["tracker"])
        self.assertEqual([p.process_calls for p in _FakeProcessor.instances], [1, 1])
        self.assertEqual(pipelines._detector.calls, 1)
        self.assertEqual(int(output[0, 0, 0]), 11)
        self.assertEqual(int(self.frame[0, 0, 0]), 0)

    def test_rejects_no_pipeline(self):
        with self.assertRaises(ValueError):
            self._make(False, False)

    def test_real_processor_counting_only_never_initializes_lpr(self):
        with patch("vehicle_counting_system.core.frame_processor.load_counting_config", return_value={}), patch(
            "vehicle_counting_system.core.frame_processor.LineCounter"
        ) as counter_cls, patch("vehicle_counting_system.core.frame_processor.LPRService") as lpr_cls:
            processor = FrameProcessor(object(), object(), enable_counting=True, enable_lpr=False)
            counter_cls.assert_called_once()
            lpr_cls.assert_not_called()
            processor.close()

    def test_real_processor_lpr_only_never_initializes_counter(self):
        with patch("vehicle_counting_system.core.frame_processor.load_counting_config", return_value={}), patch(
            "vehicle_counting_system.core.frame_processor.LineCounter"
        ) as counter_cls, patch("vehicle_counting_system.core.frame_processor.LPRService") as lpr_cls:
            processor = FrameProcessor(object(), object(), enable_counting=False, enable_lpr=True)
            counter_cls.assert_not_called()
            lpr_cls.assert_called_once()
            processor.close()


if __name__ == "__main__":
    unittest.main()
