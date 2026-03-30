"""Authenticated endpoint for media files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from vehicle_counting_system.configs.paths import OUTPUT_VIDEOS_DIR
from vehicle_counting_system.presentation.web.dependencies import require_login

def build_router() -> APIRouter:
    router = APIRouter(prefix="/media", tags=["media"])

    @router.get("/{filename:path}")
    def serve_media(request: Request, filename: str):
        # Allow either redirect (if accessed via browser) or 401 error
        user = require_login(request)
        if isinstance(user, RedirectResponse):
            return user
            
        media_dir = Path(OUTPUT_VIDEOS_DIR).resolve()
        file_path = (media_dir / filename).resolve()

        # Path traversal protection
        try:
            file_path.relative_to(media_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Forbidden")

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        # Determine media type for mp4 or standard files if needed
        return FileResponse(file_path)

    return router
