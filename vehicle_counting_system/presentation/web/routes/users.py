from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, get_current_user, require_admin


def build_router(templates) -> APIRouter:
    router = APIRouter()

    def _users_page_context(request, container, **extra):
        return base_context(
            request,
            page_title="Người dùng",
            users=container.auth_service.list_users(),
            **extra,
        )

    @router.get("/users")
    def users_page(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        return templates.TemplateResponse("users.html", _users_page_context(request, container))

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
        current = get_current_user(request)
        try:
            container.auth_service.create_user(
                username=username, password=password, full_name=full_name, role=role,
            )
            container.activity_log_service.log(
                action="create_user",
                detail=f"Tạo tài khoản '{username}' (vai trò: {role})",
                user_id=current.id if current else None,
                username=current.username if current else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/users", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "users.html", _users_page_context(request, container, error=str(exc)), status_code=400,
            )

    @router.post("/users/{user_id}/toggle-active")
    def toggle_user_active(request: Request, user_id: int):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        current = get_current_user(request)
        try:
            new_active = container.auth_service.toggle_user_active(user_id)
            target = container.auth_service.get_user(user_id)
            action_label = "Kích hoạt" if new_active else "Vô hiệu hóa"
            container.activity_log_service.log(
                action="toggle_user",
                detail=f"{action_label} tài khoản '{target.username if target else user_id}'",
                user_id=current.id if current else None,
                username=current.username if current else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/users", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "users.html", _users_page_context(request, container, error=str(exc)), status_code=400,
            )

    @router.post("/users/{user_id}/delete")
    def delete_user(request: Request, user_id: int):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        current = get_current_user(request)
        target = container.auth_service.get_user(user_id)
        target_name = target.username if target else str(user_id)
        try:
            container.auth_service.delete_user(user_id)
            container.activity_log_service.log(
                action="delete_user",
                detail=f"Xóa tài khoản '{target_name}'",
                user_id=current.id if current else None,
                username=current.username if current else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/users", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "users.html", _users_page_context(request, container, error=str(exc)), status_code=400,
            )

    @router.post("/users/{user_id}/reset-password")
    def reset_password(request: Request, user_id: int, new_password: str = Form(...)):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        current = get_current_user(request)
        try:
            target_username = container.auth_service.reset_password(user_id, new_password)
            container.activity_log_service.log(
                action="reset_password",
                detail=f"Đặt lại mật khẩu cho '{target_username}'",
                user_id=current.id if current else None,
                username=current.username if current else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/users?msg=password_reset", status_code=303)
        except Exception as exc:
            return templates.TemplateResponse(
                "users.html", _users_page_context(request, container, error=str(exc)), status_code=400,
            )

    return router
