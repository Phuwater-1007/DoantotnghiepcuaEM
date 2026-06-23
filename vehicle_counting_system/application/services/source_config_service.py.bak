# ===== file: application/services/source_config_service.py =====
"""Lưu và tải config ROI/line riêng cho mỗi source. Dùng tọa độ chuẩn hóa (0-1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vehicle_counting_system.configs.paths import CONFIG_DIR
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)

SOURCES_CONFIG_DIR = CONFIG_DIR / "sources"


def _source_config_path(source_id: int) -> Path:
    ensure_dir(SOURCES_CONFIG_DIR)
    return SOURCES_CONFIG_DIR / f"source_{source_id}.json"


def save_source_config(
    source_id: int,
    roi: list[list[float]],
    line: dict[str, Any],
) -> str:
    """
    Lưu config ROI/line cho source. Dùng tọa độ chuẩn hóa (0-1).
    Trả về đường dẫn file đã lưu.
    """
    path = _source_config_path(source_id)
    config = {
        "coordinates_mode": "normalized",
        "roi": roi,
        "lines": [line],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    logger.info("Saved source config: %s", path)
    return str(path)


def load_source_config(source_id: int) -> dict[str, Any] | None:
    """Tải config của source nếu có."""
    path = _source_config_path(source_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_source_config_path(source_id: int) -> str | None:
    """Trả về đường dẫn config nếu source đã có config riêng."""
    path = _source_config_path(source_id)
    return str(path) if path.exists() else None
