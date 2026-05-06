from __future__ import annotations

import json
from datetime import date

VN_SQLITE_TZ_MOD = "+7 hours"


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

        # ============================================================
        # TODAY stats — đọc từ vehicle_counts (đồng bộ với all-time)
        # ============================================================
        today_class_rows = self.db.fetchall(
            """
            SELECT class_name, COUNT(*) AS cnt
            FROM vehicle_counts
            WHERE date(datetime(counted_at, ?)) = ?
            GROUP BY class_name
            ORDER BY cnt DESC
            """,
            (VN_SQLITE_TZ_MOD, today),
        )
        per_class: dict[str, int] = {str(r["class_name"]): int(r["cnt"]) for r in today_class_rows}
        total = sum(per_class.values())

        completed_today_rows = self.db.fetchall(
            """
            SELECT id FROM analysis_sessions
            WHERE status = 'completed'
              AND finished_at IS NOT NULL
              AND date(datetime(finished_at, ?)) = ?
            """,
            (VN_SQLITE_TZ_MOD, today),
        )
        completed_sessions_today = len(completed_today_rows)

        # ============================================================
        # HOURLY chart — từ vehicle_counts, group theo giờ đếm
        # ============================================================
        hourly_rows = self.db.fetchall(
            """
            SELECT substr(datetime(counted_at, ?), 12, 2) AS hour_label,
                   COUNT(*) AS vehicle_count
            FROM vehicle_counts
            WHERE date(datetime(counted_at, ?)) = ?
            GROUP BY substr(datetime(counted_at, ?), 12, 2)
            ORDER BY hour_label ASC
            """,
            (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD, today, VN_SQLITE_TZ_MOD),
        )

        sources = self.source_service.list_sources()
        configured_sources = sum(1 for source in sources if source.counting_config_path)
        running_row = self.db.fetchone(
            """
            SELECT id, source_id, datetime(started_at, ?) AS started_at
            FROM analysis_sessions
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 1
            """,
            (VN_SQLITE_TZ_MOD,),
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
            SELECT sess.id, sess.status,
                   datetime(sess.started_at, ?) AS started_at,
                   CASE WHEN sess.finished_at IS NULL THEN NULL ELSE datetime(sess.finished_at, ?) END AS finished_at,
                   sess.summary_json, sess.error_message, src.name AS source_name, src.source_type
            FROM analysis_sessions sess
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.id DESC
            LIMIT 1
            """,
            (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD),
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

        # ============================================================
        # ALL-TIME stats — cũng từ vehicle_counts (luôn đồng bộ)
        # ============================================================
        alltime_row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM vehicle_counts")
        alltime_total = int(alltime_row["cnt"]) if alltime_row else 0
        alltime_class_rows = self.db.fetchall(
            "SELECT class_name, COUNT(*) AS cnt FROM vehicle_counts GROUP BY class_name ORDER BY cnt DESC"
        )
        alltime_per_class = {str(r["class_name"]): int(r["cnt"]) for r in alltime_class_rows}

        # Recent vehicle counts (last 20)
        recent_counts = self.db.fetchall(
            """
            SELECT vc.id, vc.track_id, vc.class_name, vc.confidence, vc.direction,
                   datetime(vc.counted_at, '+7 hours') AS counted_at, src.name AS source_name
            FROM vehicle_counts vc
            LEFT JOIN sources src ON src.id = vc.source_id
            ORDER BY vc.id DESC
            LIMIT 20
            """
        )
        recent_vehicle_list = [
            {
                "id": int(r["id"]),
                "track_id": int(r["track_id"]),
                "class_name": str(r["class_name"]),
                "confidence": round(float(r["confidence"]), 2),
                "direction": str(r["direction"]),
                "counted_at": str(r["counted_at"]),
                "source_name": str(r["source_name"] or ""),
            }
            for r in recent_counts
        ]

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
            "alltime_total": alltime_total,
            "alltime_per_class": alltime_per_class,
            "alltime_vehicle_mix": self._aggregate_vehicle_mix(alltime_per_class),
            "recent_vehicle_counts": recent_vehicle_list,
        }
