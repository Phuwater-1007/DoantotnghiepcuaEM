"""Service dành cho chức năng admin: thống kê hệ thống, quản lý dữ liệu."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from vehicle_counting_system.configs.paths import (
    APP_DB_PATH,
    DATA_DIR,
    INPUT_VIDEOS_DIR,
    OUTPUT_CSV_DIR,
    OUTPUT_LOGS_DIR,
    OUTPUT_VIDEOS_DIR,
)
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


class AdminService:
    def __init__(self, db, monitoring_service):
        self.db = db
        self.monitoring_service = monitoring_service

    @staticmethod
    def _dir_size(path: Path) -> int:
        """Tính tổng dung lượng thư mục (bytes)."""
        total = 0
        if not path.exists():
            return 0
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _count_files(path: Path, extensions: set[str] | None = None) -> int:
        if not path.exists():
            return 0
        count = 0
        for f in path.iterdir():
            if f.is_file():
                if extensions is None or f.suffix.lower() in extensions:
                    count += 1
        return count

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def get_system_stats(self) -> dict[str, Any]:
        """Thu thập thông tin thống kê hệ thống."""
        # Database stats
        db_size = 0
        db_path = Path(APP_DB_PATH)
        if db_path.exists():
            db_size = db_path.stat().st_size

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        total_users = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM sources")
        total_sources = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM analysis_sessions")
        total_sessions = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM analysis_sessions WHERE status = 'completed'")
        completed_sessions = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM analysis_sessions WHERE status = 'failed'")
        failed_sessions = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM report_snapshots")
        total_reports = int(row["cnt"]) if row else 0

        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM activity_logs")
        total_logs = int(row["cnt"]) if row else 0

        # File stats
        video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
        input_video_count = self._count_files(INPUT_VIDEOS_DIR, video_extensions)
        output_video_count = self._count_files(OUTPUT_VIDEOS_DIR, video_extensions)
        input_dir_size = self._dir_size(INPUT_VIDEOS_DIR)
        output_dir_size = self._dir_size(OUTPUT_VIDEOS_DIR)
        csv_dir_size = self._dir_size(OUTPUT_CSV_DIR)
        logs_dir_size = self._dir_size(OUTPUT_LOGS_DIR)

        return {
            "db_size": db_size,
            "db_size_display": self._format_size(db_size),
            "total_users": total_users,
            "total_sources": total_sources,
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "failed_sessions": failed_sessions,
            "total_reports": total_reports,
            "total_logs": total_logs,
            "input_video_count": input_video_count,
            "output_video_count": output_video_count,
            "input_dir_size": input_dir_size,
            "input_dir_size_display": self._format_size(input_dir_size),
            "output_dir_size": output_dir_size,
            "output_dir_size_display": self._format_size(output_dir_size),
            "csv_dir_size_display": self._format_size(csv_dir_size),
            "logs_dir_size_display": self._format_size(logs_dir_size),
            "total_storage": self._format_size(input_dir_size + output_dir_size + csv_dir_size + logs_dir_size + db_size),
        }

    def clear_sessions_and_reports(self) -> dict[str, int]:
        """Xóa toàn bộ phiên phân tích và báo cáo (reset demo)."""
        if self.monitoring_service.get_active_session_id() is not None:
            raise RuntimeError("Đang có phiên phân tích chạy. Vui lòng dừng trước khi xóa.")

        r1 = self.db.fetchone("SELECT COUNT(*) AS cnt FROM report_snapshots")
        r2 = self.db.fetchone("SELECT COUNT(*) AS cnt FROM analysis_sessions")

        self.db.execute("DELETE FROM report_snapshots")
        self.db.execute("DELETE FROM analysis_sessions")

        try:
            self.db.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('analysis_sessions', 'report_snapshots')"
            )
        except Exception:
            pass

        return {
            "reports_deleted": int(r1["cnt"]) if r1 else 0,
            "sessions_deleted": int(r2["cnt"]) if r2 else 0,
        }

    def clear_output_videos(self) -> dict[str, int]:
        """Xóa toàn bộ video output đã xử lý."""
        if self.monitoring_service.get_active_session_id() is not None:
            raise RuntimeError("Đang có phiên phân tích chạy. Vui lòng dừng trước khi xóa.")

        deleted_count = 0
        for directory in (OUTPUT_VIDEOS_DIR, OUTPUT_CSV_DIR, OUTPUT_LOGS_DIR):
            path = Path(directory)
            if not path.exists():
                continue
            for child in path.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                        deleted_count += 1
                    except OSError:
                        logger.warning("Cannot delete: %s", child)

        return {"files_deleted": deleted_count}
