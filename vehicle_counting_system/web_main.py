from __future__ import annotations

import os
import threading
import time
import webbrowser
from dataclasses import dataclass

import uvicorn

from vehicle_counting_system.presentation.web.app import create_app


@dataclass
class AutoShutdownConfig:
    enabled: bool = True
    idle_seconds: float = 10.0
    wait_for_active_session: bool = True
    # If we haven't received an explicit disconnect (`active_tabs` stays 1),
    # we still shut down after "no heartbeat" persists for longer than idle_seconds.
    active_tabs_grace_multiplier: float = 2.0
    # When we receive an explicit disconnect (active_tabs becomes 0),
    # shutdown immediately (with tiny debounce).
    disconnect_debounce_seconds: float = 0.2


class ShutdownController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reason: str | None = None

    def request(self, reason: str) -> None:
        with self._lock:
            self._reason = reason

    def reason(self) -> str | None:
        with self._lock:
            return self._reason


def _watch_for_no_clients(app, controller: ShutdownController, cfg: AutoShutdownConfig) -> None:
    if not cfg.enabled:
        return
    while controller.reason() is None:
        time.sleep(0.2)
        presence = getattr(app.state, "client_presence", None)
        container = getattr(app.state, "container", None)
        if presence is None or container is None:
            continue
        snap = presence.snapshot()
        if snap.last_seen_ts <= 0:
            continue
        # If we got an explicit "tab closed" signal, request shutdown almost immediately.
        if snap.active_tabs == 0 and (time.time() - snap.last_seen_ts) >= cfg.disconnect_debounce_seconds:
            controller.request("no_browser_tabs")
            continue
        # Decide based on "no heartbeat received".
        # - When the browser explicitly disconnects, `active_tabs` becomes 0,
        #   and we wait exactly `idle_seconds`.
        # - When disconnect beacon is missed, `active_tabs` can remain 1,
        #   so we use a grace multiplier to avoid killing during transient stalls.
        no_heartbeat_for = time.time() - snap.last_seen_ts
        required_idle = cfg.idle_seconds
        if snap.active_tabs > 0:
            required_idle = cfg.idle_seconds * cfg.active_tabs_grace_multiplier

        if no_heartbeat_for >= required_idle:
            # If an analysis session is still active, optionally do not auto-shutdown.
            try:
                active_session_id = container.monitoring_service.get_active_session_id()
                explicit_disconnect = snap.active_tabs == 0
                # Only block shutdown for active sessions when we *didn't*
                # receive an explicit browser disconnect (e.g. transient stalls).
                if cfg.wait_for_active_session and active_session_id is not None and not explicit_disconnect:
                    continue
            except Exception:
                pass

            controller.request("no_browser_tabs")


def main() -> int:
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    # Default: disable auto-shutdown (manual stop like traditional servers).
    # Set `WEB_AUTO_SHUTDOWN=1` to enable the heartbeat-based shutdown behavior.
    auto_shutdown = os.getenv("WEB_AUTO_SHUTDOWN", "0").strip() not in ("0", "false", "False")
    idle_seconds = float(os.getenv("WEB_AUTO_SHUTDOWN_IDLE_SECONDS", "10"))
    wait_for_active_session = os.getenv("WEB_AUTO_SHUTDOWN_WAIT_FOR_ACTIVE_SESSION", "1").strip() not in (
        "0",
        "false",
        "False",
    )
    active_tabs_grace_multiplier = float(
        os.getenv("WEB_AUTO_SHUTDOWN_ACTIVE_TABS_GRACE_MULTIPLIER", "2.0")
    )
    disconnect_debounce_seconds = float(os.getenv("WEB_AUTO_SHUTDOWN_DISCONNECT_DEBOUNCE_SECONDS", "0.2"))

    app = create_app()
    controller = ShutdownController()
    app.state.shutdown_controller = controller

    # Reset session numbering for each web start (demo behavior).
    try:
        app.state.container.monitoring_service.reset_sessions_only()
    except Exception:
        pass

    cfg = AutoShutdownConfig(
        enabled=auto_shutdown,
        idle_seconds=idle_seconds,
        wait_for_active_session=wait_for_active_session,
        active_tabs_grace_multiplier=active_tabs_grace_multiplier,
        disconnect_debounce_seconds=disconnect_debounce_seconds,
    )
    watcher = threading.Thread(target=_watch_for_no_clients, args=(app, controller, cfg), daemon=True)
    watcher.start()

    url = f"http://{host}:{port}/monitoring"
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    def _server_watchdog() -> None:
        while not server.should_exit:
            time.sleep(0.1)
            if controller.reason() is not None:
                try:
                    app.state.container.monitoring_service.stop_active_session()
                except Exception:
                    pass
                server.should_exit = True

    threading.Thread(target=_server_watchdog, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

