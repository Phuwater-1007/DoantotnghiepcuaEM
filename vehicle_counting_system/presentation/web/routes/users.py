from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, require_admin


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/users")
    def users_page(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        return templates.TemplateResponse(
            "users.html",
            base_context(
                request,
                page_title="Người dùng",
                users=container.auth_service.list_users(),
            ),
        )

    @router.post("/users")
    def create_user(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(...),
        role: str = Form(...),
    ):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        try:
            container.auth_service.create_user(
                username=username,
                password=password,
                full_name=full_name,
                role=role,
            )
            return RedirectResponse("/users", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "users.html",
                base_context(
                    request,
                    page_title="Người dùng",
                    error=str(exc),
                    users=container.auth_service.list_users(),
                ),
                status_code=400,
            )

    return router
