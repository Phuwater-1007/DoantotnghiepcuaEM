from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from vehicle_counting_system.application.bootstrap import build_container
from vehicle_counting_system.configs.paths import INPUT_VIDEOS_DIR, OUTPUT_VIDEOS_DIR
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.presentation.web.routes import api, auth, dashboard, monitoring, reports, sources, users
from vehicle_counting_system.utils.logger import get_logger
from vehicle_counting_system.presentation.web.client_presence import ClientPresence


logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Traffic Monitoring System", version="1.0.0")

    session_secret = os.getenv("TRAFFIC_MONITORING_SESSION_SECRET")
    if not session_secret:
        session_secret = secrets.token_urlsafe(32)
        logger.warning(
            "TRAFFIC_MONITORING_SESSION_SECRET is not set. Generated an ephemeral session secret for this process."
        )

    app.add_middleware(SessionMiddleware, secret_key=session_secret)
    app.state.container = build_container()
    # Không reset output files - giữ kết quả từ VS Code (run_with_web_roi.py)
    app.state.client_presence = ClientPresence()

    templates_dir = Path(__file__).resolve().parent / "templates"
    static_dir = Path(__file__).resolve().parent / "static"
    templates = Jinja2Templates(directory=str(templates_dir))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    ensure_dir(INPUT_VIDEOS_DIR)
    ensure_dir(OUTPUT_VIDEOS_DIR)
    media_dir = Path(OUTPUT_VIDEOS_DIR).resolve()
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    app.include_router(api.build_router())
    app.include_router(auth.build_router(templates))
    app.include_router(dashboard.build_router(templates))
    app.include_router(monitoring.build_router(templates))
    app.include_router(sources.build_router(templates))
    app.include_router(reports.build_router(templates))
    app.include_router(users.build_router(templates))

    return app
