"""WebSocket endpoints for real-time monitoring and dashboard updates.

Replaces the HTTP polling pattern (setInterval + fetch /api/monitoring/live-state)
with a persistent WebSocket connection.  The server pushes updates whenever
MonitoringService has new data, or at most every PUSH_INTERVAL_S seconds.

Endpoints
---------
/ws/monitoring  — live analysis stats for the Monitoring page
/ws/dashboard   — merged headless + stream stats for the Dashboard page
/ws/app-status  — lightweight status check (nav live dot, heartbeat replacement)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)

# How often (seconds) the server pushes data even without explicit change
PUSH_INTERVAL_S = 0.3   # ≈ 300 ms — much faster than the old 800 ms poll
DASHBOARD_PUSH_S = 1.0  # Dashboard updates are less time-critical
STATUS_PUSH_S = 2.0     # App-wide status (nav dot) every 2 s


def _get_container(websocket: WebSocket):
    """Pull the DI container from the app state."""
    return websocket.app.state.container


def _get_monitoring_payload(container) -> dict[str, Any]:
    """Build the monitoring live-state payload (no image_data)."""
    active_id = container.monitoring_service.get_active_session_id()
    live_state = container.monitoring_service.get_live_state()

    # Strip heavy base64 frame — video is served via MJPEG stream already
    if live_state and "image_data" in live_state:
        live_state = {k: v for k, v in live_state.items() if k != "image_data"}

    # If no headless active session, try to find an active stream session ID
    is_stream_active = False
    if active_id is None:
        try:
            from vehicle_counting_system.presentation.web.routes.stream import _active_streams, _registry_lock
            with _registry_lock:
                active_sessions = list(_active_streams.values())
            if active_sessions:
                # Find first active stream session that has a valid DB session ID
                for sess in active_sessions:
                    if sess.db_session_id is not None:
                        active_id = sess.db_session_id
                        is_stream_active = True
                        break
        except Exception:
            pass

    lpr_events = []
    if active_id is not None:
        try:
            lpr_events = container.lpr_persistence_service.get_events_for_session(active_id, limit=30)
        except Exception:
            pass

    return {
        "type": "monitoring",
        "active_session_id": active_id,
        "is_stream_active": is_stream_active,
        "live_state": live_state,
        "lpr_events": lpr_events,
        "ts": time.time(),
    }


def _get_stream_stats() -> dict[str, Any]:
    """Pull aggregated stats from all active MJPEG stream sessions."""
    try:
        # Import here to avoid circular dependency
        from vehicle_counting_system.presentation.web.routes.stream import _active_streams, _registry_lock
        import threading

        with _registry_lock:
            snapshot = list(_active_streams.items())

        streams = []
        for source_id, session in snapshot:
            with session.lock:
                stats = dict(session.last_stats)
            streams.append({
                "source_id": source_id,
                "total": stats.get("total", 0),
                "per_class": stats.get("per_class", {}),
            })

        agg_total = sum(s["total"] for s in streams)
        agg_per_class: dict[str, int] = {}
        for s in streams:
            for k, v in s["per_class"].items():
                agg_per_class[k] = agg_per_class.get(k, 0) + v

        return {
            "has_active_stream": len(streams) > 0,
            "stream_count": len(streams),
            "total": agg_total,
            "per_class": agg_per_class,
            "streams": streams,
        }
    except Exception:
        return {"has_active_stream": False, "stream_count": 0, "total": 0, "per_class": {}, "streams": []}


def _get_dashboard_payload(container) -> dict[str, Any]:
    """Build the merged dashboard payload (headless + stream + DB counts)."""
    active_id = container.monitoring_service.get_active_session_id()
    live_state = container.monitoring_service.get_live_state()
    stream_stats = _get_stream_stats()

    headless_payload = None
    if live_state and "image_data" in live_state:
        live_state = {k: v for k, v in live_state.items() if k != "image_data"}
    if live_state:
        headless_payload = live_state

    # --- DB vehicle_counts (persisted, always up-to-date) ---
    from datetime import date
    today = date.today().isoformat()
    VN_TZ = "+7 hours"
    db = container.db

    # Today totals from vehicle_counts
    today_class_rows = db.fetchall(
        """
        SELECT class_name, COUNT(*) AS cnt
        FROM vehicle_counts
        WHERE date(datetime(counted_at, ?)) = ?
        GROUP BY class_name
        """,
        (VN_TZ, today),
    )
    today_per_class = {str(r["class_name"]): int(r["cnt"]) for r in today_class_rows}
    today_total = sum(today_per_class.values())

    # All-time totals
    alltime_row = db.fetchone("SELECT COUNT(*) AS cnt FROM vehicle_counts")
    alltime_total = int(alltime_row["cnt"]) if alltime_row else 0
    alltime_class_rows = db.fetchall(
        "SELECT class_name, COUNT(*) AS cnt FROM vehicle_counts GROUP BY class_name"
    )
    alltime_per_class = {str(r["class_name"]): int(r["cnt"]) for r in alltime_class_rows}

    # Hourly activity from vehicle_counts (today)
    hourly_rows = db.fetchall(
        """
        SELECT substr(datetime(counted_at, ?), 12, 2) AS hour_label,
               COUNT(*) AS vehicle_count
        FROM vehicle_counts
        WHERE date(datetime(counted_at, ?)) = ?
        GROUP BY substr(datetime(counted_at, ?), 12, 2)
        ORDER BY hour_label ASC
        """,
        (VN_TZ, VN_TZ, today, VN_TZ),
    )
    hourly_activity = [
        {"hour": str(r["hour_label"]), "count": int(r["vehicle_count"])}
        for r in hourly_rows
    ]

    return {
        "type": "dashboard",
        "active_session_id": active_id,
        "live_state": headless_payload,
        "stream_stats": stream_stats,
        "db_today_total": today_total,
        "db_today_per_class": today_per_class,
        "db_alltime_total": alltime_total,
        "db_alltime_per_class": alltime_per_class,
        "db_hourly_activity": hourly_activity,
        "ts": time.time(),
    }


def build_router() -> APIRouter:
    router = APIRouter(tags=["websocket"])

    # ------------------------------------------------------------------
    # /ws/monitoring  — real-time analysis state for Monitoring page
    # ------------------------------------------------------------------
    @router.websocket("/ws/monitoring")
    async def ws_monitoring(websocket: WebSocket):
        await websocket.accept()
        logger.info("WS /ws/monitoring: client connected from %s", websocket.client)
        container = _get_container(websocket)

        try:
            while True:
                payload = _get_monitoring_payload(container)
                await websocket.send_text(json.dumps(payload, ensure_ascii=False, default=str))
                await asyncio.sleep(PUSH_INTERVAL_S)

        except WebSocketDisconnect:
            logger.info("WS /ws/monitoring: client disconnected")
        except Exception as exc:
            logger.warning("WS /ws/monitoring error: %s", exc)

    # ------------------------------------------------------------------
    # /ws/dashboard  — merged live stats for Dashboard page
    # ------------------------------------------------------------------
    @router.websocket("/ws/dashboard")
    async def ws_dashboard(websocket: WebSocket):
        await websocket.accept()
        logger.info("WS /ws/dashboard: client connected from %s", websocket.client)
        container = _get_container(websocket)

        try:
            while True:
                payload = _get_dashboard_payload(container)
                await websocket.send_text(json.dumps(payload, ensure_ascii=False, default=str))
                await asyncio.sleep(DASHBOARD_PUSH_S)

        except WebSocketDisconnect:
            logger.info("WS /ws/dashboard: client disconnected")
        except Exception as exc:
            logger.warning("WS /ws/dashboard error: %s", exc)

    # ------------------------------------------------------------------
    # /ws/app-status  — lightweight status for nav live dot (all pages)
    # ------------------------------------------------------------------
    @router.websocket("/ws/app-status")
    async def ws_app_status(websocket: WebSocket):
        await websocket.accept()
        logger.info("WS /ws/app-status: client connected from %s", websocket.client)
        container = _get_container(websocket)

        try:
            while True:
                active_id = container.monitoring_service.get_active_session_id()
                stream_stats = _get_stream_stats()
                payload = {
                    "type": "app_status",
                    "active_session_id": active_id,
                    "has_active_stream": stream_stats.get("has_active_stream", False),
                    "ts": time.time(),
                }
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(STATUS_PUSH_S)

        except WebSocketDisconnect:
            logger.info("WS /ws/app-status: client disconnected")
        except Exception as exc:
            logger.warning("WS /ws/app-status error: %s", exc)

    return router
