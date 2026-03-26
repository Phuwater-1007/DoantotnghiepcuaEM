from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from vehicle_counting_system.configs.paths import OUTPUT_CSV_DIR
from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.models.statistics import Statistics
from vehicle_counting_system.utils.file_utils import ensure_dir


class ExportService:
    def __init__(
        self,
        csv_dir: str | Path = OUTPUT_CSV_DIR,
        class_names: Iterable[str] | None = None,
    ):
        self.csv_dir = Path(csv_dir)
        ensure_dir(self.csv_dir)
        default_classes = class_names if class_names is not None else settings.allowed_class_names
        self.class_names = sorted({name.strip() for name in default_classes if name.strip()})

    def _summary_row(self, stats: Statistics) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "total": stats.total,
            "per_class": dict(sorted(stats.per_class.items())),
        }

    def _csv_fieldnames(self) -> list[str]:
        fields = ["timestamp", "total"]
        fields.extend(f"class_{name}" for name in self.class_names)
        fields.append("class_other")
        return fields

    def _summary_csv_row(self, stats: Statistics) -> Dict[str, Any]:
        row = self._summary_row(stats)
        per_class = row["per_class"]
        flat_row: Dict[str, Any] = {
            "timestamp": row["timestamp"],
            "total": row["total"],
        }
        other_total = 0
        for name in self.class_names:
            flat_row[f"class_{name}"] = int(per_class.get(name, 0))
        for name, count in per_class.items():
            if name not in self.class_names:
                other_total += int(count)
        flat_row["class_other"] = other_total
        return flat_row

    def export_summary_csv(self, stats: Statistics, filename: str = "summary.csv") -> Path:
        """
        Write a single-row summary CSV with a stable, thesis-friendly schema.
        If the file exists, append a new row using the same field order.
        """
        path = self.csv_dir / filename
        flat_row = self._summary_csv_row(stats)
        fieldnames = self._csv_fieldnames()

        write_header = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(flat_row)

        return path

    def export_summary_json(self, stats: Statistics, filename: str = "summary.json") -> Path:
        """
        Append a JSON entry to a list stored in summary.json (easy to report/plot later).
        """
        path = self.csv_dir / filename
        row = self._summary_row(stats)

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        else:
            data = []

        data.append(row)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

