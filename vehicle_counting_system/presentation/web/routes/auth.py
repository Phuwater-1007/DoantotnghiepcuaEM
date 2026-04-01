from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, get_current_user, _ensure_csrf_token


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
            # Log failed login attempt
            container.activity_log_service.log(
                action="login_failed",
                detail=f"Đăng nhập thất bại cho '{username}'",
                ip_address=request.client.host if request.client else "",
            )
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
        request.session["instance_id"] = request.app.state.instance_id
        
        # Log successful login
        container.activity_log_service.log(
            action="login",
            detail=f"Đăng nhập thành công",
            user_id=user.id,
            username=user.username,
            ip_address=request.client.host if request.client else "",
        )
        return RedirectResponse("/dashboard", status_code=303)

    @router.post("/logout")
    def logout(request: Request):
        container = get_container(request)
        user = get_current_user(request)
        if user:
            container.activity_log_service.log(
                action="logout",
                detail="Đăng xuất",
                user_id=user.id,
                username=user.username,
                ip_address=request.client.host if request.client else "",
            )
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @router.get("/access-denied")
    def access_denied_page(request: Request):
        user = get_current_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        if user.role == "admin":
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(
            "access_denied.html",
            base_context(request, page_title="Không có quyền truy cập"),
            status_code=403,
        )

    return router
