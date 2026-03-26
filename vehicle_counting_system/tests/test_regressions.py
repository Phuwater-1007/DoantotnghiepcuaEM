import csv
import tempfile
import unittest
from pathlib import Path

from vehicle_counting_system.counters.line_counter import LineCounter
from vehicle_counting_system.models.statistics import Statistics
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.services.export_service import ExportService
from vehicle_counting_system.utils.file_utils import ensure_dir


class TestRegressions(unittest.TestCase):
    def test_ensure_dir_with_file_path_creates_parent_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_file = Path(tmp_dir) / "videos" / "result.mp4"
            created_dir = ensure_dir(output_file)

            self.assertEqual(created_dir, output_file.parent)
            self.assertTrue(output_file.parent.exists())
            self.assertFalse(output_file.exists())
            self.assertFalse(output_file.is_dir())

    def test_line_counter_requires_segment_intersection(self):
        counter = LineCounter([((10, 0), (10, 10))], line_directions=["both"])

        first = TrackedObject(
            track_id=1,
            class_id=2,
            class_name="car",
            bbox=(0, 0, 0, 0),
            history=[(5.0, 20.0)],
        )
        second = TrackedObject(
            track_id=1,
            class_id=2,
            class_name="car",
            bbox=(0, 0, 0, 0),
            history=[(15.0, 20.0)],
        )

        counter.process([first])
        stats = counter.process([second])

        self.assertEqual(stats.total, 0)
        self.assertEqual(stats.per_class, {})

    def test_export_service_uses_stable_csv_schema(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exporter = ExportService(tmp_dir, class_names=["car", "truck"])

            stats_a = Statistics(total=2, per_class={"car": 2})
            stats_b = Statistics(total=3, per_class={"truck": 1, "bus": 2})

            csv_path = exporter.export_summary_csv(stats_a)
            exporter.export_summary_csv(stats_b)

            with open(csv_path, newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

            self.assertEqual(
                rows[0].keys(),
                rows[1].keys(),
            )
            self.assertIn("class_car", rows[0])
            self.assertIn("class_truck", rows[0])
            self.assertIn("class_other", rows[0])
            self.assertEqual(rows[0]["class_truck"], "0")
            self.assertEqual(rows[1]["class_other"], "2")


if __name__ == "__main__":
    unittest.main()
