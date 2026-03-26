from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, require_login, to_media_url


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/reports")
    def reports_page(request: Request):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        container = get_container(request)
        reports = container.report_service.list_reports()
        for report in reports:
            output_path = report.get("output_video_path")
            report["media_url"] = to_media_url(output_path) if output_path else None
        report_summary = {
            "total_reports": len(reports),
            "total_vehicles": sum(r["total"] for r in reports),
        }
        return templates.TemplateResponse(
            "reports.html",
            base_context(
                request,
                page_title="Báo cáo",
                reports=reports,
                report_summary=report_summary,
            ),
        )

    return router
