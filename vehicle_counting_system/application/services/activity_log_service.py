"""Service ghi nhật ký hoạt động hệ thống."""
from __future__ import annotations

from typing import Any


class ActivityLogService:
    def __init__(self, db):
        self.db = db

    def log(
        self,
        action: str,
        detail: str = "",
        user_id: int | None = None,
        username: str = "",
        ip_address: str = "",
    ) -> None:
        """Ghi một entry vào nhật ký hoạt động."""
        self.db.execute(
            """
            INSERT INTO activity_logs (user_id, username, action, detail, ip_address)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, action, detail, ip_address),
        )

    def list_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Lấy danh sách nhật ký hoạt động, mới nhất trước."""
        rows = self.db.fetchall(
            """
            SELECT id, user_id, username, action, detail, ip_address,
                   datetime(created_at, 'localtime') AS created_at
            FROM activity_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (min(limit, 500),),
        )
        return [
            {
                "id": int(row["id"]),
                "user_id": row["user_id"],
                "username": str(row["username"]),
                "action": str(row["action"]),
                "detail": str(row["detail"]),
                "ip_address": str(row["ip_address"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def clear_logs(self) -> int:
        """Xóa toàn bộ nhật ký. Trả về số dòng đã xóa."""
        count_row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM activity_logs")
        count = int(count_row["cnt"]) if count_row else 0
        self.db.execute("DELETE FROM activity_logs")
        return count
