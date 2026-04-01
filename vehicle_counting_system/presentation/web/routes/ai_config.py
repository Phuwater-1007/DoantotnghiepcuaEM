from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from vehicle_counting_system.presentation.web.dependencies import base_context, get_container, require_admin
from vehicle_counting_system.ai_core.services.video_analysis_runner import get_ai_config, update_ai_config

def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/ai-config", response_class=HTMLResponse)
    def ai_config_page(request: Request, user=Depends(require_admin)):
        # Chỉ Admin mới được vào trang này
        config = get_ai_config()
        container = get_container(request)
        
        # Get recent activity logs for alerts
        logs = container.activity_log_service.list_logs(limit=30)
        
        ctx = base_context(request, page_title="Tối ưu AI & Cảnh báo")
        ctx["ai_config"] = config
        ctx["logs"] = logs
        
        return templates.TemplateResponse("ai_optimization.html", ctx)

    @router.post("/ai-config", response_class=HTMLResponse)
    def update_ai_config_action(
        request: Request,
        conf_threshold: float = Form(...),
        min_box_area: float = Form(...),
        user=Depends(require_admin)
    ):
        try:
            update_ai_config(conf_thres=conf_threshold, min_box_area=min_box_area)
            container = get_container(request)
            container.activity_log_service.log(
                action="update_ai_config",
                detail=f"Cập nhật cấu hình AI: Conf={conf_threshold}, Min Area={min_box_area}",
                user_id=user.id,
                username=user.username,
                ip_address=request.client.host if request.client else "",
            )
            
            # Re-render the page with success message
            config = get_ai_config()
            logs = container.activity_log_service.list_logs(limit=20)
            ctx = base_context(request, page_title="Tối ưu AI & Cảnh báo")
            ctx["ai_config"] = config
            ctx["logs"] = logs
            ctx["success_message"] = "Đã cập nhật thông số AI thành công! Thay đổi sẽ áp dụng ngay ở phiên giám sát tiếp theo."
            
            return templates.TemplateResponse("ai_optimization.html", ctx)
        except Exception as e:
            config = get_ai_config()
            container = get_container(request)
            logs = container.activity_log_service.list_logs(limit=20)
            ctx = base_context(request, page_title="Tối ưu AI & Cảnh báo")
            ctx["ai_config"] = config
            ctx["logs"] = logs
            ctx["error"] = f"Lỗi cập nhật: {str(e)}"
            return templates.TemplateResponse("ai_optimization.html", ctx, status_code=400)

    return router
