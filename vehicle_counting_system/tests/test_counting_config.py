import json
import tempfile
import unittest
from pathlib import Path

from vehicle_counting_system.configs.counting_config import load_counting_config


class TestCountingConfig(unittest.TestCase):
    def test_invalid_editable_roi_falls_back_to_base_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            base_path = config_dir / "counting_lines.json"
            editable_path = config_dir / "editable_roi.json"

            base_path.write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "base",
                                "start": [1, 2],
                                "end": [3, 4],
                                "direction": "both",
                            }
                        ],
                        "roi": [[10, 10], [20, 10], [20, 20], [10, 20]],
                    }
                ),
                encoding="utf-8",
            )
            editable_path.write_text("{ invalid json", encoding="utf-8")

            config = load_counting_config(str(base_path))

            self.assertEqual(config["lines"][0]["id"], "base")
            self.assertEqual(config["roi"][0], [10, 10])

    def test_valid_editable_roi_overrides_base_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            base_path = config_dir / "counting_lines.json"
            editable_path = config_dir / "editable_roi.json"

            base_path.write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "base",
                                "start": [1, 2],
                                "end": [3, 4],
                                "direction": "both",
                            }
                        ],
                        "roi": [[10, 10], [20, 10], [20, 20], [10, 20]],
                    }
                ),
                encoding="utf-8",
            )
            editable_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "line": {
                            "id": "user",
                            "start": [100, 200],
                            "end": [300, 200],
                            "direction": "both",
                        },
                        "roi": [[1, 1], [9, 1], [9, 9], [1, 9]],
                    }
                ),
                encoding="utf-8",
            )

            config = load_counting_config(str(base_path))

            self.assertEqual(config["lines"][0]["id"], "user")
            self.assertEqual(config["lines"][0]["start"], [100, 200])
            self.assertEqual(config["roi"][0], [1, 1])


if __name__ == "__main__":
    unittest.main()
