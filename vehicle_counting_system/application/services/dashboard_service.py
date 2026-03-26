from __future__ import annotations

import json
from datetime import date


class DashboardService:
    def __init__(self, db, source_service):
        self.db = db
        self.source_service = source_service

    @staticmethod
    def _aggregate_vehicle_mix(per_class: dict[str, int]) -> dict[str, int]:
        motorcycle = int(per_class.get("motorcycle", 0))
        automobile = int(per_class.get("car", 0)) + int(per_class.get("truck", 0)) + int(per_class.get("bus", 0))
        return {
            "motorcycle": motorcycle,
            "automobile": automobile,
            "car": int(per_class.get("car", 0)),
            "truck": int(per_class.get("truck", 0)),
            "bus": int(per_class.get("bus", 0)),
        }

    def get_dashboard_data(self) -> dict:
        today = date.today().isoformat()
        rows = self.db.fetchall(
            """
            SELECT rs.total, rs.per_class_json, s.status, s.name
            FROM report_snapshots rs
            JOIN analysis_sessions sess ON sess.id = rs.session_id
            JOIN sources s ON s.id = sess.source_id
            WHERE rs.report_date = ?
            """,
            (today,),
        )

        completed_today_rows = self.db.fetchall(
            """
            SELECT id FROM analysis_sessions
            WHERE finished_at IS NOT NULL
              AND date(finished_at) = ?
            """,
            (today,),
        )
        completed_sessions_today = len(completed_today_rows)

        total = 0
        per_class: dict[str, int] = {}
        for row in rows:
            total += int(row["total"])
            raw = json.loads(row["per_class_json"] or "{}")
            for key, value in raw.items():
                per_class[key] = per_class.get(key, 0) + int(value)

        hourly_rows = self.db.fetchall(
            """
            SELECT substr(sess.started_at, 12, 2) AS hour_label, COALESCE(SUM(rs.total), 0) AS vehicle_count
            FROM analysis_sessions sess
            LEFT JOIN report_snapshots rs ON rs.session_id = sess.id
            WHERE date(sess.started_at) = ?
            GROUP BY substr(sess.started_at, 12, 2)
            ORDER BY hour_label ASC
            """,
            (today,),
        )
        sources = self.source_service.list_sources()
        configured_sources = sum(1 for source in sources if source.counting_config_path)
        running_row = self.db.fetchone(
            """
            SELECT id, source_id, started_at
            FROM analysis_sessions
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 1
            """
        )

        hourly_activity = [
            {"hour": str(row["hour_label"]), "count": int(row["vehicle_count"])}
            for row in hourly_rows
        ]
        peak_hour = None
        max_hourly_count = 1
        if hourly_activity:
            peak_hour = max(hourly_activity, key=lambda x: x["count"])["hour"] + ":00"
            max_hourly_count = max(c["count"] for c in hourly_activity)

        latest_row = self.db.fetchone(
            """
            SELECT sess.id, sess.status, sess.started_at, sess.finished_at,
                   sess.summary_json, sess.error_message, src.name AS source_name, src.source_type
            FROM analysis_sessions sess
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.id DESC
            LIMIT 1
            """
        )
        latest_session = None
        if latest_row:
            summary = json.loads(latest_row["summary_json"] or "{}")
            latest_session = {
                "id": int(latest_row["id"]),
                "status": str(latest_row["status"]),
                "started_at": str(latest_row["started_at"]),
                "finished_at": latest_row["finished_at"],
                "summary": summary,
                "vehicle_mix": self._aggregate_vehicle_mix(summary.get("per_class", {})),
                "error_message": latest_row["error_message"],
                "source_name": str(latest_row["source_name"]),
                "source_type": str(latest_row["source_type"]),
            }

        vehicle_mix = self._aggregate_vehicle_mix(per_class)

        return {
            "today_total": total,
            "per_class": per_class,
            "vehicle_mix": vehicle_mix,
            "hourly_activity": hourly_activity,
            "completed_sessions_today": completed_sessions_today,
            "peak_hour": peak_hour,
            "max_hourly_count": max_hourly_count,
            "latest_session": latest_session,
            "sources_total": len(sources),
            "configured_sources": configured_sources,
            "running_session": dict(running_row) if running_row else None,
        }
