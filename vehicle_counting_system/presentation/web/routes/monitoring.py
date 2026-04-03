from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import (
    base_context,
    get_container,
    list_input_videos,
    list_output_videos,
    require_login,
    to_media_url,
)


def _build_monitoring_page_data(container) -> dict:
    detected_videos = list_input_videos()
    for video in detected_videos:
        source = container.source_service.get_source_by_uri(video["path"])
        video["roi_ready"] = bool(source and source.counting_config_path)
        video["source_id"] = source.id if source else None
        video["roi_edit_url"] = (
            f"/monitoring/edit-roi-for-video?path={video['path']}"
        )

    sessions = container.monitoring_service.list_sessions(limit=8)
    latest_completed_session = None
    for session in sessions:
        session["media_url"] = to_media_url(session["output_video_path"])
        if latest_completed_session is None and session["status"] == "completed" and session["media_url"]:
            latest_completed_session = session

    return {
        "sources": container.source_service.list_sources(),
        "output_videos": list_output_videos(),
        "detected_videos": detected_videos,
        "active_session_id": container.monitoring_service.get_active_session_id(),
        "latest_completed_session": latest_completed_session,
    }


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/monitoring")
    def monitoring_page(request: Request):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        return templates.TemplateResponse(
            "monitoring.html",
            base_context(
                request,
                page_title="Giám sát",
                **_build_monitoring_page_data(container),
            ),
        )

    @router.post("/monitoring/start")
    def start_monitoring(request: Request, source_id: int = Form(...)):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        try:
            container.monitoring_service.start_session(source_id=source_id, user_id=user.id)
            return RedirectResponse("/monitoring", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "monitoring.html",
                base_context(
                    request,
                    page_title="Giám sát",
                    error=str(exc),
                    **_build_monitoring_page_data(container),
                ),
                status_code=400,
            )

    @router.get("/monitoring/edit-roi-for-video")
    def edit_roi_for_video(request: Request, path: str = ""):
        """Tạo source từ video path (nếu chưa có) và chuyển đến trang chỉnh ROI."""
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        if not path or not path.strip():
            return RedirectResponse("/monitoring", status_code=303)
        container = get_container(request)
        try:
            source = container.source_service.get_or_create_source_for_video(path.strip())
            return RedirectResponse(f"/sources/{source.id}/edit-roi", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "monitoring.html",
                base_context(
                    request,
                    page_title="Giám sát",
                    error=f"Không thể mở chỉnh ROI: {exc}",
                    **_build_monitoring_page_data(container),
                ),
                status_code=400,
            )

    @router.get("/sources/{source_id}/edit-roi")
    def edit_roi_page(request: Request, source_id: int):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return RedirectResponse("/monitoring", status_code=303)
        return templates.TemplateResponse(
            "edit_roi.html",
            base_context(
                request,
                page_title=f"Chỉnh ROI - {source.name}",
                source=source,
            ),
        )

    @router.post("/monitoring/stop")
    def stop_monitoring(request: Request):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        container.monitoring_service.stop_active_session()
        return RedirectResponse("/monitoring", status_code=303)

    return router
