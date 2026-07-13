from __future__ import annotations

import json

VN_SQLITE_TZ_MOD = "+7 hours"


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
                datetime(sess.started_at, ?) AS started_at,
                CASE WHEN sess.finished_at IS NULL THEN NULL ELSE datetime(sess.finished_at, ?) END AS finished_at,
                sess.output_video_path,
                src.name AS source_name
            FROM report_snapshots rs
            JOIN analysis_sessions sess ON sess.id = rs.session_id
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.started_at DESC
            """,
            (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD),
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

    def get_report_details(self, session_id: int) -> dict | None:
        # 1. Fetch report snapshot and analysis session metadata
        row = self.db.fetchone(
            """
            SELECT
                rs.session_id,
                rs.report_date,
                rs.total,
                rs.per_class_json,
                rs.peak_hour_label,
                sess.status,
                datetime(sess.started_at, ?) AS started_at,
                CASE WHEN sess.finished_at IS NULL THEN NULL ELSE datetime(sess.finished_at, ?) END AS finished_at,
                sess.output_video_path,
                src.name AS source_name
            FROM report_snapshots rs
            JOIN analysis_sessions sess ON sess.id = rs.session_id
            JOIN sources src ON src.id = sess.source_id
            WHERE rs.session_id = ?
            """,
            (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD, session_id),
        )
        if not row:
            # Fallback check if the session exists but snapshot isn't generated yet (e.g. running or failed session)
            row = self.db.fetchone(
                """
                SELECT
                    sess.id AS session_id,
                    datetime(sess.started_at, ?) AS started_at,
                    CASE WHEN sess.finished_at IS NULL THEN NULL ELSE datetime(sess.finished_at, ?) END AS finished_at,
                    sess.status,
                    sess.output_video_path,
                    sess.summary_json,
                    src.name AS source_name
                FROM analysis_sessions sess
                JOIN sources src ON src.id = sess.source_id
                WHERE sess.id = ?
                """,
                (VN_SQLITE_TZ_MOD, VN_SQLITE_TZ_MOD, session_id),
            )
            if not row:
                return None
            
            # Populate dummy snapshot data for running/failed sessions
            summary = json.loads(row["summary_json"] or "{}")
            metadata = {
                "session_id": int(row["session_id"]),
                "report_date": row["started_at"][:10] if row["started_at"] else "N/A",
                "total": int(summary.get("total", 0)),
                "per_class": summary.get("per_class", {}),
                "peak_hour_label": "N/A",
                "status": str(row["status"]),
                "started_at": str(row["started_at"]),
                "finished_at": row["finished_at"],
                "source_name": str(row["source_name"]),
                "output_video_path": row["output_video_path"],
            }
        else:
            metadata = {
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

        # 2. Fetch LPR Events
        lpr_rows = self.db.fetchall(
            """
            SELECT
                datetime(created_at, ?) AS created_at,
                vehicle_class,
                license_plate,
                confidence,
                plate_image_path
            FROM license_plate_events
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (VN_SQLITE_TZ_MOD, session_id),
        )
        lpr_events = []
        for lpr in lpr_rows:
            lpr_events.append({
                "created_at": str(lpr["created_at"]),
                "vehicle_class": str(lpr["vehicle_class"]),
                "license_plate": str(lpr["license_plate"]),
                "confidence": float(lpr["confidence"]),
                "plate_image_path": lpr["plate_image_path"],
            })

        # 3. Fetch Vehicle Counts for Time Binning
        counts_rows = self.db.fetchall(
            """
            SELECT
                datetime(counted_at, ?) AS counted_at,
                class_name,
                direction
            FROM vehicle_counts
            WHERE session_id = ?
            ORDER BY counted_at ASC
            """,
            (VN_SQLITE_TZ_MOD, session_id),
        )

        # Dynamic Binning Algorithm
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        start_dt = None
        end_dt = None
        if metadata["started_at"] and metadata["started_at"] != "None":
            try:
                start_dt = datetime.strptime(metadata["started_at"], fmt)
            except Exception:
                pass
        if metadata["finished_at"] and metadata["finished_at"] != "None":
            try:
                end_dt = datetime.strptime(metadata["finished_at"], fmt)
            except Exception:
                pass
        
        # Fallbacks for end_dt
        if not end_dt and start_dt:
            if counts_rows:
                try:
                    end_dt = datetime.strptime(counts_rows[-1]["counted_at"], fmt)
                except Exception:
                    end_dt = datetime.now()
            else:
                end_dt = datetime.now()

        duration_sec = 0
        if start_dt and end_dt:
            duration_sec = max(0, (end_dt - start_dt).total_seconds())

        # Select appropriate bin size in seconds
        if duration_sec <= 60:
            bin_size = 5
        elif duration_sec <= 300:
            bin_size = 15
        elif duration_sec <= 1800:
            bin_size = 60
        elif duration_sec <= 7200:
            bin_size = 300
        else:
            bin_size = 600

        # Calculate number of bins
        if duration_sec > 0:
            num_bins = int(duration_sec / bin_size) + 1
            if num_bins > 60:
                num_bins = 60
                bin_size = duration_sec / num_bins
        else:
            num_bins = 1
            bin_size = 60

        bins = []
        start_ts = start_dt.timestamp() if start_dt else datetime.now().timestamp()
        for i in range(num_bins):
            b_start = start_ts + i * bin_size
            b_end = b_start + bin_size
            # Format label
            if duration_sec <= 300:
                label = f"+{int(i * bin_size)}s"
            else:
                label = datetime.fromtimestamp(b_start).strftime("%H:%M:%S")
            bins.append({
                "label": label,
                "start": b_start,
                "end": b_end,
                "counts": {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "total": 0}
            })

        # Fill bins
        for row in counts_rows:
            try:
                dt = datetime.strptime(row["counted_at"], fmt)
                ts = dt.timestamp()
            except Exception:
                continue

            for b in bins:
                if b["start"] <= ts < b["end"]:
                    cls = row["class_name"].lower()
                    if cls in ["car", "automobile"]:
                        cls = "car"
                    elif cls in ["motorcycle", "motorbike"]:
                        cls = "motorcycle"
                    
                    if cls in b["counts"]:
                        b["counts"][cls] += 1
                    b["counts"]["total"] += 1
                    break

        # Calculate In/Out flow stats
        direction_counts = {"in": 0, "out": 0, "unknown": 0}
        for row in counts_rows:
            d = str(row["direction"]).lower()
            if d in ["in", "đến", "đi vào"]:
                direction_counts["in"] += 1
            elif d in ["out", "đi", "đi ra"]:
                direction_counts["out"] += 1
            else:
                direction_counts["unknown"] += 1

        chart_data = {
            "labels": [b["label"] for b in bins],
            "total": [b["counts"]["total"] for b in bins],
            "car": [b["counts"]["car"] for b in bins],
            "motorcycle": [b["counts"]["motorcycle"] for b in bins],
            "bus": [b["counts"]["bus"] for b in bins],
            "truck": [b["counts"]["truck"] for b in bins]
        }

        return {
            "metadata": metadata,
            "lpr_events": lpr_events,
            "chart_data": chart_data,
            "direction_counts": direction_counts,
            "duration_formatted": f"{int(duration_sec // 60)} phút {int(duration_sec % 60)} giây" if duration_sec > 0 else "N/A"
        }

    def get_detailed_vehicles_csv(self, session_ids: list[int]) -> str:
        if not session_ids:
            return ""
        
        # Build query placeholders
        placeholders = ",".join("?" for _ in session_ids)
        query = f"""
            SELECT
                datetime(vc.counted_at, ?) AS time_formatted,
                vc.class_name,
                vc.track_id,
                vc.confidence,
                src.name AS source_name,
                vc.session_id
            FROM vehicle_counts vc
            JOIN sources src ON src.id = vc.source_id
            WHERE vc.session_id IN ({placeholders})
            ORDER BY vc.session_id DESC, vc.counted_at ASC
        """
        
        params = [VN_SQLITE_TZ_MOD] + session_ids
        rows = self.db.fetchall(query, tuple(params))
        
        # Translate helper
        def translate_class(cls_name: str) -> str:
            c = cls_name.lower().strip()
            if c in ["car", "automobile"]:
                return "Ô tô"
            elif c in ["motorcycle", "motorbike", "bicycle"]:
                return "Xe máy"
            elif c in ["bus"]:
                return "Xe buýt"
            elif c in ["truck"]:
                return "Xe tải"
            return cls_name.capitalize()

        import io
        import csv
        
        output = io.StringIO()
        
        writer = csv.writer(output, lineterminator="\n")
        # Write headers
        writer.writerow(["Thời gian", "Loại xe", "Track ID", "Độ tin cậy", "Camera", "Phiên"])
        
        for r in rows:
            conf = float(r["confidence"])
            conf_str = f"{int(round(conf * 100))}%" if conf > 0 else "N/A"
            
            # Format time to show only HH:MM:SS as in user's request screenshot
            time_str = r["time_formatted"]
            if time_str and " " in time_str:
                time_str = time_str.split(" ")[1]

            writer.writerow([
                time_str,
                translate_class(r["class_name"]),
                r["track_id"],
                conf_str,
                r["source_name"],
                f"#{r['session_id']}"
            ])
            
        return output.getvalue()
