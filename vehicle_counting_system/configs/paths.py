from __future__ import annotations

from pathlib import Path

# `vehicle_counting_system/` directory
PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_DIR = PROJECT_ROOT / "configs"
DATA_DIR = PROJECT_ROOT / "data"

DATA_INPUT_DIR = DATA_DIR / ("inputs" if (DATA_DIR / "inputs").exists() else "input")
DATA_OUTPUT_DIR = DATA_DIR / ("outputs" if (DATA_DIR / "outputs").exists() else "output")

INPUT_VIDEOS_DIR = DATA_INPUT_DIR / "videos"

OUTPUT_VIDEOS_DIR = DATA_OUTPUT_DIR / "videos"
OUTPUT_CSV_DIR = DATA_OUTPUT_DIR / "csv"
OUTPUT_LOGS_DIR = DATA_OUTPUT_DIR / "logs"
OUTPUT_APP_DIR = DATA_OUTPUT_DIR / "app"
APP_DB_PATH = OUTPUT_APP_DIR / "traffic_monitoring.db"

MODELS_DIR = DATA_DIR / "models"

