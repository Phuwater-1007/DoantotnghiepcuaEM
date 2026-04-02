from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from vehicle_counting_system.application.bootstrap import build_container
from vehicle_counting_system.configs.paths import INPUT_VIDEOS_DIR, OUTPUT_VIDEOS_DIR
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.presentation.web.routes import admin, api, auth, dashboard, media, monitoring, reports, ai_config, stream, users
from vehicle_counting_system.utils.logger import get_logger
from vehicle_counting_system.presentation.web.client_presence import ClientPresence


logger = get_logger(__name__)


def create_app() -> FastAPI:
    import uuid
    app = FastAPI(title="Traffic Monitoring System", version="1.0.0")
    
    # Generate a unique ID for this specific server run
    # This forces users to log in again every time the server restarts
    app.state.instance_id = str(uuid.uuid4())

    session_secret = os.getenv("TRAFFIC_MONITORING_SESSION_SECRET")
    is_production = os.getenv("TRAFFIC_MONITORING_ENV", "development").lower() == "production"

    if not session_secret:
        if is_production:
            raise ValueError("TRAFFIC_MONITORING_SESSION_SECRET environment variable must be set in production")
        session_secret = secrets.token_urlsafe(32)
        logger.warning(
            "TRAFFIC_MONITORING_SESSION_SECRET is not set. Generated an ephemeral session secret for this development process."
        )

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(
        SessionMiddleware, 
        secret_key=session_secret, 
        max_age=None,  # Session cookie: hết hạn khi đóng trình duyệt
        https_only=is_production, 
        same_site="lax" if not is_production else "strict"
    )
    app.state.container = build_container()
    # Không reset output files - giữ kết quả từ VS Code (run_with_web_roi.py)
    app.state.client_presence = ClientPresence()

    templates_dir = Path(__file__).resolve().parent / "templates"
    static_dir = Path(__file__).resolve().parent / "static"
    templates = Jinja2Templates(directory=str(templates_dir))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    ensure_dir(INPUT_VIDEOS_DIR)
    ensure_dir(OUTPUT_VIDEOS_DIR)


    app.include_router(api.build_router())
    app.include_router(auth.build_router(templates))
    app.include_router(dashboard.build_router(templates))
    app.include_router(monitoring.build_router(templates))
    app.include_router(reports.build_router(templates))
    app.include_router(ai_config.build_router(templates))
    app.include_router(stream.build_router())
    app.include_router(users.build_router(templates))
    app.include_router(admin.build_router(templates))
    app.include_router(media.build_router())

    return app


# ---------------------------------------------------------------------------
# Lightweight CSRF middleware
# ---------------------------------------------------------------------------
_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_SKIP_PATHS = {"/api/"}  # JSON API uses auth tokens; forms use CSRF


class CSRFMiddleware:
    """Validates a csrf_token form field on state-changing form submissions.

    Skips:
    - Safe HTTP methods (GET, HEAD, OPTIONS)
    - Paths starting with /api/ (use existing auth)
    - Requests with Content-Type: application/json (API clients)
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)

        if request.method in _CSRF_SAFE_METHODS:
            return await self.app(scope, receive, send)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _CSRF_SKIP_PATHS):
            return await self.app(scope, receive, send)

        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            return await self.app(scope, receive, send)

        # Buffer the body to read form safely without starving downstream apps
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        async def mock_receive():
            return {"type": "http.request", "body": body}

        req_copy = Request(scope, mock_receive)
        
        session_token = req_copy.session.get("csrf_token")
        if not session_token:
            req_copy.session["csrf_token"] = secrets.token_urlsafe(32)
            response = JSONResponse(status_code=403, content={"error": "CSRF token missing. Please reload the page."})
            return await response(scope, mock_receive, send)
            
        form = await req_copy.form()
        form_token = form.get("csrf_token", "")
        if not secrets.compare_digest(str(session_token), str(form_token)):
            response = JSONResponse(status_code=403, content={"error": "CSRF token invalid. Please reload the page."})
            return await response(scope, mock_receive, send)

        # CSRF valid! Replay the body to the actual app
        messages = [{"type": "http.request", "body": body}]
        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b""}

        return await self.app(scope, replay_receive, send)
