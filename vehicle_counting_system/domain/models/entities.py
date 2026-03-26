from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class User:
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool


@dataclass
class Source:
    id: int
    name: str
    source_type: str
    source_uri: str
    is_active: bool
    status: str
    notes: str
    counting_config_path: str | None = None


@dataclass
class AnalysisSession:
    id: int
    source_id: int
    started_by: int
    status: str
    started_at: str
    finished_at: str | None
    output_video_path: str | None
    summary_json: dict[str, Any]
    error_message: str | None
