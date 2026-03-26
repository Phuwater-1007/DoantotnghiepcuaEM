from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, get_current_user


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/login")
    def login_page(request: Request):
        if get_current_user(request) is not None:
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(
            "login.html",
            base_context(request, page_title="Đăng nhập"),
        )

    @router.post("/login")
    def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
        container = get_container(request)
        user = container.auth_service.authenticate(username, password)
        if user is None:
            return templates.TemplateResponse(
                "login.html",
                base_context(
                    request,
                    page_title="Đăng nhập",
                    error="Tên đăng nhập hoặc mật khẩu không đúng.",
                ),
                status_code=400,
            )

        request.session["user_id"] = user.id
        return RedirectResponse("/dashboard", status_code=303)

    @router.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    return router
