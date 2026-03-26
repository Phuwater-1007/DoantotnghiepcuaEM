from __future__ import annotations

from pathlib import Path

from vehicle_counting_system.configs.paths import PROJECT_ROOT
from vehicle_counting_system.domain.models.entities import Source
from vehicle_counting_system.utils.file_utils import VIDEO_EXTENSIONS


def _resolve_path(raw: str) -> Path:
    """Resolve path: absolute as-is, relative against PROJECT_ROOT."""
    p = Path(raw.strip())
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def validate_source_paths(
    source_uri: str,
    counting_config_path: str | None,
) -> tuple[str, str | None]:
    """
    Validate video and config paths exist. Returns (resolved_source_uri, resolved_config_path).
    Raises ValueError with clear message if invalid.
    """
    if not source_uri or not source_uri.strip():
        raise ValueError("Source path is required.")

    video_path = _resolve_path(source_uri)
    if not video_path.exists():
        raise ValueError(f"Video file not found: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Source path is not a file: {video_path}")
    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported video format. Allowed: {', '.join(sorted(VIDEO_EXTENSIONS))}"
        )

    resolved_config: str | None = None
    if counting_config_path and counting_config_path.strip():
        config_path = _resolve_path(counting_config_path.strip())
        if not config_path.exists():
            raise ValueError(f"Counting config file not found: {config_path}")
        if not config_path.is_file():
            raise ValueError(f"Counting config path is not a file: {config_path}")
        resolved_config = str(config_path)

    return str(video_path), resolved_config


class SourceService:
    _SUPPORTED_SOURCE_TYPES = {"video"}

    def __init__(self, db):
        self.db = db

    def list_sources(self) -> list[Source]:
        rows = self.db.fetchall(
            """
            SELECT id, name, source_type, source_uri, is_active, status, notes, counting_config_path
            FROM sources
            ORDER BY is_active DESC, id ASC
            """
        )
        return [
            Source(
                id=int(row["id"]),
                name=str(row["name"]),
                source_type=str(row["source_type"]),
                source_uri=str(row["source_uri"]),
                is_active=bool(row["is_active"]),
                status=str(row["status"]),
                notes=str(row["notes"] or ""),
                counting_config_path=row["counting_config_path"],
            )
            for row in rows
        ]

    def get_source(self, source_id: int) -> Source | None:
        row = self.db.fetchone(
            """
            SELECT id, name, source_type, source_uri, is_active, status, notes, counting_config_path
            FROM sources
            WHERE id = ?
            """,
            (source_id,),
        )
        if row is None:
            return None
        return Source(
            id=int(row["id"]),
            name=str(row["name"]),
            source_type=str(row["source_type"]),
            source_uri=str(row["source_uri"]),
            is_active=bool(row["is_active"]),
            status=str(row["status"]),
            notes=str(row["notes"] or ""),
            counting_config_path=row["counting_config_path"],
        )

    def create_source(
        self,
        name: str,
        source_type: str,
        source_uri: str,
        notes: str = "",
        counting_config_path: str | None = None,
    ) -> None:
        normalized_type = source_type.strip().lower()
        if normalized_type not in self._SUPPORTED_SOURCE_TYPES:
            raise ValueError("Current web product only supports offline video sources.")

        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Source name is required.")

        resolved_uri, resolved_config = validate_source_paths(
            source_uri, counting_config_path or None
        )
        existing = self.get_source_by_uri(resolved_uri)
        if existing is not None:
            raise ValueError("Video này đã tồn tại trong danh sách nguồn.")

        self.db.execute(
            """
            INSERT INTO sources (name, source_type, source_uri, notes, counting_config_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cleaned_name,
                normalized_type,
                resolved_uri,
                notes.strip(),
                resolved_config,
                "ready",
            ),
        )

    def get_source_by_uri(self, source_uri: str) -> Source | None:
        """Tìm source theo source_uri (relative hoặc absolute). Ưu tiên source đã có config ROI."""
        try:
            resolved = str(_resolve_path(source_uri))
        except Exception:
            return None
        rows = self.db.fetchall(
            """
            SELECT id
            FROM sources
            WHERE source_uri = ?
            ORDER BY
                CASE WHEN counting_config_path IS NOT NULL AND TRIM(counting_config_path) != '' THEN 0 ELSE 1 END,
                is_active DESC,
                id ASC
            """,
            (resolved,),
        )
        if not rows:
            return None
        return self.get_source(int(rows[0]["id"]))

    def get_or_create_source_for_video(self, video_path: str) -> Source:
        """Tìm hoặc tạo source cho video. Trả về Source."""
        existing = self.get_source_by_uri(video_path)
        if existing:
            return existing
        resolved, _ = validate_source_paths(video_path, None)
        name = Path(resolved).stem
        self.db.execute(
            """
            INSERT INTO sources (name, source_type, source_uri, notes, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, "video", resolved, "Tự động thêm", "ready"),
        )
        row = self.db.fetchone("SELECT id FROM sources ORDER BY id DESC LIMIT 1")
        return self.get_source(int(row["id"]))

    def update_counting_config(self, source_id: int, config_path: str | None) -> None:
        """Cập nhật đường dẫn config đếm cho source."""
        self.db.execute(
            """
            UPDATE sources SET counting_config_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (config_path, source_id),
        )

    def activate_source(self, source_id: int) -> None:
        self.db.execute(
            """
            UPDATE sources
            SET is_active = CASE WHEN id = ? THEN 1 ELSE 0 END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (source_id,),
        )

    def get_active_source(self) -> Source | None:
        row = self.db.fetchone(
            """
            SELECT id, name, source_type, source_uri, is_active, status, notes, counting_config_path
            FROM sources
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )
        if row is None:
            return None
        return Source(
            id=int(row["id"]),
            name=str(row["name"]),
            source_type=str(row["source_type"]),
            source_uri=str(row["source_uri"]),
            is_active=bool(row["is_active"]),
            status=str(row["status"]),
            notes=str(row["notes"] or ""),
            counting_config_path=row["counting_config_path"],
        )
