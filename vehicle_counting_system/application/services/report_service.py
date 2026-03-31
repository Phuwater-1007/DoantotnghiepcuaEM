from __future__ import annotations

import json


class ReportService:
    def __init__(self, db):
        self.db = db

    def list_reports(self) -> list[dict]:
        rows = self.db.fetchall(
            """
            SELECT
                rs.id,
                rs.session_id,
                rs.report_date,
                rs.total,
                rs.per_class_json,
                rs.peak_hour_label,
                sess.status,
                datetime(sess.started_at, 'localtime') AS started_at,
                CASE WHEN sess.finished_at IS NULL THEN NULL ELSE datetime(sess.finished_at, 'localtime') END AS finished_at,
                sess.output_video_path,
                src.name AS source_name
            FROM report_snapshots rs
            JOIN analysis_sessions sess ON sess.id = rs.session_id
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.started_at DESC
            """
        )
        reports: list[dict] = []
        for row in rows:
            reports.append(
                {
                    "id": int(row["id"]),
                    "session_id": int(row["session_id"]),
                    "report_date": str(row["report_date"]),
                    "total": int(row["total"]),
                    "per_class": json.loads(row["per_class_json"] or "{}"),
                    "peak_hour_label": str(row["peak_hour_label"]),
                    "status": str(row["status"]),
                    "started_at": str(row["started_at"]),
                    "finished_at": row["finished_at"],
                    "source_name": str(row["source_name"]),
                    "output_video_path": row["output_video_path"],
                }
            )
        return reports

    def save_report_snapshot(self, session_id: int, finished_at: str, total: int, per_class: dict[str, int]) -> None:
        # Use finished_at for report_date so midnight-crossing sessions are dated correctly
        report_date = finished_at[:10] if len(finished_at) >= 10 else "N/A"
        peak_hour_label = finished_at[11:13] + ":00" if len(finished_at) >= 13 else "N/A"
        self.db.execute(
            """
            INSERT OR REPLACE INTO report_snapshots (session_id, report_date, total, per_class_json, peak_hour_label)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                report_date,
                total,
                json.dumps(per_class, ensure_ascii=False),
                peak_hour_label,
            ),
        )
