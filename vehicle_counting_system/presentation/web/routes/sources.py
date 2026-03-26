from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, list_input_videos, require_login


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/sources")
    def sources_page(request: Request):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        return templates.TemplateResponse(
            "sources.html",
            base_context(
                request,
                page_title="Thư viện video",
                sources=container.source_service.list_sources(),
                detected_videos=list_input_videos(),
            ),
        )

    @router.post("/sources")
    def create_source(
        request: Request,
        name: str = Form(...),
        source_type: str = Form(...),
        source_uri: str = Form(...),
        notes: str = Form(""),
        counting_config_path: str = Form(""),
    ):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        try:
            container.source_service.create_source(
                name=name,
                source_type=source_type,
                source_uri=source_uri,
                notes=notes,
                counting_config_path=counting_config_path or None,
            )
            return RedirectResponse("/sources", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "sources.html",
                base_context(
                    request,
                    page_title="Thư viện video",
                    error=str(exc),
                    sources=container.source_service.list_sources(),
                    detected_videos=list_input_videos(),
                ),
                status_code=400,
            )

    @router.post("/sources/{source_id}/activate")
    def activate_source(request: Request, source_id: int):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        container.source_service.activate_source(source_id)
        return RedirectResponse("/sources", status_code=303)

    @router.get("/sources/{source_id}/edit-roi")
    def edit_roi_page(request: Request, source_id: int):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return RedirectResponse("/sources", status_code=303)
        if source.source_type != "video":
            return RedirectResponse("/sources", status_code=303)
        return templates.TemplateResponse(
            "edit_roi.html",
            base_context(
                request,
                page_title=f"Chỉnh ROI/Line - {source.name}",
                source=source,
            ),
        )

    return router
