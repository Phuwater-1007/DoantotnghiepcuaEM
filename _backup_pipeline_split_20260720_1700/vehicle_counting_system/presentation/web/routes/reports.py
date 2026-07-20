from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Response

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

    @router.get("/api/export-reports")
    def export_detailed_csv_api(request: Request, sessions: str):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return user
        
        try:
            session_ids = [int(s.strip()) for s in sessions.split(",") if s.strip()]
        except ValueError:
            return {"error": "Invalid session IDs"}
            
        container = get_container(request)
        csv_str = container.report_service.get_detailed_vehicles_csv(session_ids)
        
        # Encode as UTF-8 with BOM (utf-8-sig)
        csv_bytes = csv_str.encode("utf-8-sig")
        
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=ChiTiet_PhuongTien.csv"
            }
        )

    @router.get("/api/reports/{session_id}")
    def get_report_details_api(request: Request, session_id: int):
        user = require_login(request)
        if hasattr(user, "status_code"):
            return {"error": "Unauthorized"}
        
        container = get_container(request)
        details = container.report_service.get_report_details(session_id)
        if not details:
            return {"error": "Report not found"}
        
        # Build media url if possible
        output_path = details["metadata"].get("output_video_path")
        details["metadata"]["media_url"] = to_media_url(output_path) if output_path else None
        
        return details

    return router
