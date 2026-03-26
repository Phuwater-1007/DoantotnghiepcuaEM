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
    idle_seconds: float = 1.2


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
        # If analysis is running, we still allow shutdown when user closes the tab.
        # The server watchdog will stop the active session before exiting.
        if snap.last_seen_ts <= 0:
            continue
        if (time.time() - snap.last_seen_ts) >= cfg.idle_seconds:
            controller.request("no_browser_tabs")


def main() -> int:
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    auto_shutdown = os.getenv("WEB_AUTO_SHUTDOWN", "1").strip() not in ("0", "false", "False")
    idle_seconds = float(os.getenv("WEB_AUTO_SHUTDOWN_IDLE_SECONDS", "1.2"))

    app = create_app()
    controller = ShutdownController()
    app.state.shutdown_controller = controller

    # Reset session numbering for each web start (demo behavior).
    try:
        app.state.container.monitoring_service.reset_sessions_only()
    except Exception:
        pass

    cfg = AutoShutdownConfig(enabled=auto_shutdown, idle_seconds=idle_seconds)
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
                server.should_exit = True
                try:
                    app.state.container.monitoring_service.stop_active_session()
                except Exception:
                    pass

    threading.Thread(target=_server_watchdog, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

