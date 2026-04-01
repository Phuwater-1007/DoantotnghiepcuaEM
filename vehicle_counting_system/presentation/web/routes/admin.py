"""Admin panel routes: system stats, data management, activity log."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, get_current_user, require_admin


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/admin")
    def admin_page(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        stats = container.admin_service.get_system_stats()
        logs = container.activity_log_service.list_logs(limit=50)
        return templates.TemplateResponse(
            "admin.html",
            base_context(
                request,
                page_title="Quản trị hệ thống",
                stats=stats,
                logs=logs,
            ),
        )

    @router.post("/admin/clear-sessions")
    def clear_sessions(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        user = get_current_user(request)
        try:
            result = container.admin_service.clear_sessions_and_reports()
            container.activity_log_service.log(
                action="clear_sessions",
                detail=f"Đã xóa {result['sessions_deleted']} phiên, {result['reports_deleted']} báo cáo",
                user_id=user.id if user else None,
                username=user.username if user else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/admin", status_code=303)
        except Exception as exc:
            stats = container.admin_service.get_system_stats()
            logs = container.activity_log_service.list_logs(limit=50)
            return templates.TemplateResponse(
                "admin.html",
                base_context(request, page_title="Quản trị hệ thống", stats=stats, logs=logs, error=str(exc)),
                status_code=400,
            )

    @router.post("/admin/clear-output")
    def clear_output(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        user = get_current_user(request)
        try:
            result = container.admin_service.clear_output_videos()
            container.activity_log_service.log(
                action="clear_output",
                detail=f"Đã xóa {result['files_deleted']} file output",
                user_id=user.id if user else None,
                username=user.username if user else "",
                ip_address=request.client.host if request.client else "",
            )
            return RedirectResponse("/admin", status_code=303)
        except Exception as exc:
            stats = container.admin_service.get_system_stats()
            logs = container.activity_log_service.list_logs(limit=50)
            return templates.TemplateResponse(
                "admin.html",
                base_context(request, page_title="Quản trị hệ thống", stats=stats, logs=logs, error=str(exc)),
                status_code=400,
            )

    @router.post("/admin/clear-logs")
    def clear_logs(request: Request):
        admin = require_admin(request)
        if hasattr(admin, "status_code"):
            return admin
        container = get_container(request)
        user = get_current_user(request)
        count = container.activity_log_service.clear_logs()
        # Log the clear action itself (so log is never truly empty)
        container.activity_log_service.log(
            action="clear_logs",
            detail=f"Đã xóa {count} nhật ký cũ",
            user_id=user.id if user else None,
            username=user.username if user else "",
            ip_address=request.client.host if request.client else "",
        )
        return RedirectResponse("/admin", status_code=303)

    return router
