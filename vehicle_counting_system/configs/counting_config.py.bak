from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vehicle_counting_system.configs.paths import CONFIG_DIR
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)

BASE_COUNTING_CONFIG_PATH = CONFIG_DIR / "counting_lines.json"
EDITABLE_ROI_CONFIG_PATH = CONFIG_DIR / "editable_roi.json"


def _as_point(value: Any, normalized: bool = False) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Invalid point: {value!r}")
    x, y = float(value[0]), float(value[1])
    if normalized:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"Normalized point must be in [0,1]: {value!r}")
    return x, y


def _scale_point(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    return int(round(x * width)), int(round(y * height))


def _validate_roi(raw_roi: Any, normalized: bool = False) -> list[list[float]]:
    if raw_roi in (None, []):
        return []
    if not isinstance(raw_roi, list) or len(raw_roi) < 3:
        raise ValueError("ROI must contain at least 3 points.")
    roi: list[list[float]] = []
    for point in raw_roi:
        x, y = _as_point(point, normalized=normalized)
        roi.append([x, y])
    return roi


def _validate_line(raw_line: Any, normalized: bool = False) -> dict[str, Any]:
    if not isinstance(raw_line, dict):
        raise ValueError("Line override must be an object.")
    start = _as_point(raw_line.get("start"), normalized=normalized)
    end = _as_point(raw_line.get("end"), normalized=normalized)
    direction = str(raw_line.get("direction", "both")).lower()
    if direction not in {"both", "p1_to_p2", "p2_to_p1"}:
        raise ValueError(f"Invalid direction: {direction!r}")
    line_id = str(raw_line.get("id", "main_road_downstream"))
    return {
        "id": line_id,
        "start": [start[0], start[1]],
        "end": [end[0], end[1]],
        "direction": direction,
    }


def _scale_config_to_pixels(
    config: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    """Scale normalized lines/roi to pixel coordinates."""
    out = dict(config)
    if "roi" in out and out["roi"]:
        out["roi"] = [
            list(_scale_point(p[0], p[1], width, height))
            for p in out["roi"]
        ]
    if "lines" in out and out["lines"]:
        out["lines"] = [
            {
                **line,
                "start": list(_scale_point(line["start"][0], line["start"][1], width, height)),
                "end": list(_scale_point(line["end"][0], line["end"][1], width, height)),
            }
            for line in out["lines"]
        ]
    return out


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a JSON object: {path}")
    return data


def load_counting_config(
    counting_lines_path: str | None = None,
    frame_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """
    Load counting config. Supports:
    - coordinates_mode "pixel" (default): absolute [x,y] pixels
    - coordinates_mode "normalized": [0-1] relative to frame; pass frame_size to scale

    When frame_size=(width, height) is given and mode is normalized, lines/roi
    are scaled to pixels so one config works for multiple resolutions.
    """
    base_path = Path(counting_lines_path) if counting_lines_path else BASE_COUNTING_CONFIG_PATH
    config = _load_json(base_path)

    editable_path: Path | None = EDITABLE_ROI_CONFIG_PATH
    if counting_lines_path:
        editable_path = None
        candidate = Path(counting_lines_path).with_name("editable_roi.json")
        if candidate.exists():
            editable_path = candidate

    _config_before_editable = dict(config)
    if editable_path is not None and editable_path.exists():
        try:
            editable = _load_json(editable_path)
            if bool(editable.get("enabled", True)):
                if "roi" in editable:
                    config["roi"] = editable.get("roi")
                if "line" in editable:
                    config["lines"] = [editable.get("line")]
                logger.info("Loaded editable ROI override from %s", editable_path)
        except Exception as exc:
            logger.warning(
                "Ignoring editable ROI override: %s | file=%s",
                exc,
                editable_path,
            )

    normalized = str(config.get("coordinates_mode", "pixel")).lower() == "normalized"

    def validate_and_convert(cfg: dict[str, Any]) -> dict[str, Any]:
        out = dict(cfg)
        if out.get("roi"):
            roi = _validate_roi(out["roi"], normalized=normalized)
            out["roi"] = [[int(x), int(y)] for x, y in roi] if not normalized else roi
        if out.get("lines"):
            lines = [_validate_line(L, normalized=normalized) for L in out["lines"]]
            if not normalized:
                for L in lines:
                    L["start"] = [int(L["start"][0]), int(L["start"][1])]
                    L["end"] = [int(L["end"][0]), int(L["end"][1])]
            out["lines"] = lines
        return out

    try:
        config = validate_and_convert(config)
    except ValueError:
        if config != _config_before_editable:
            logger.warning(
                "Editable ROI/line incompatible with coordinates_mode=%s, using base config",
                "normalized" if normalized else "pixel",
            )
            config = validate_and_convert(_config_before_editable)
        else:
            raise

    if normalized and frame_size:
        w, h = int(frame_size[0]), int(frame_size[1])
        if w > 0 and h > 0:
            config = _scale_config_to_pixels(config, w, h)
            logger.info("Scaled normalized config to %dx%d", w, h)

    return config
