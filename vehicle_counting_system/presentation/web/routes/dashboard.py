from __future__ import annotations

from fastapi import APIRouter, Request

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, require_login


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    @router.get("/dashboard")
    def dashboard(request: Request):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        dashboard_data = container.dashboard_service.get_dashboard_data()
        return templates.TemplateResponse(
            "dashboard.html",
            base_context(
                request,
                page_title="Bảng điều khiển",
                dashboard=dashboard_data,
            ),
        )

    return router
