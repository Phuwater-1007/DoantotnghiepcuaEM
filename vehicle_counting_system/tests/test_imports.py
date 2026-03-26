import unittest


class TestImports(unittest.TestCase):
    def test_import_core(self):
        import vehicle_counting_system.core.pipeline  # noqa: F401
        import vehicle_counting_system.core.frame_processor  # noqa: F401

    def test_import_modules(self):
        import vehicle_counting_system.detectors.yolo_detector  # noqa: F401
        import vehicle_counting_system.trackers.bytetrack_tracker  # noqa: F401
        import vehicle_counting_system.counters.line_counter  # noqa: F401


if __name__ == "__main__":
    unittest.main()

