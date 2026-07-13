from __future__ import annotations

import json
import shutil
from pathlib import Path
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from vehicle_counting_system.configs.paths import DATA_DIR
from vehicle_counting_system.presentation.web.dependencies import (
    base_context,
    require_admin,
)


def build_router(templates) -> APIRouter:
    router = APIRouter()
    settings_file = DATA_DIR / "system_settings.json"
    static_dir = Path(__file__).resolve().parent.parent / "static"

    @router.get("/brand-settings")
    def brand_settings_page(request: Request):
        # Yêu cầu quyền admin để cấu hình thương hiệu
        user = require_admin(request)
        if hasattr(user, "status_code"):
            return user

        # Đọc cấu hình hiện tại
        settings = {
            "company_name": "Giám sát Giao thông",
            "subtitle": "Đồ án tốt nghiệp",
            "logo_url": "/static/brand_logo.jpg",
            "address": "",
        }
        if settings_file.exists():
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    settings.update(data)
            except Exception:
                pass

        success = request.session.pop("settings_success", None)
        error = request.session.pop("settings_error", None)

        return templates.TemplateResponse(
            "brand_settings.html",
            base_context(
                request,
                page_title="Đơn vị sử dụng",
                settings=settings,
                success_msg=success,
                error_msg=error,
            ),
        )

    @router.post("/brand-settings/save")
    async def save_brand_settings(
        request: Request,
        company_name: str = Form(...),
        address: str = Form(""),
        logo_file: UploadFile = File(None),
    ):
        user = require_admin(request)
        if hasattr(user, "status_code"):
            return user

        try:
            # Đọc cấu hình cũ
            settings = {
                "company_name": "Giám sát Giao thông",
                "subtitle": "Đồ án tốt nghiệp",
                "logo_url": "/static/brand_logo.jpg",
                "address": "",
            }
            if settings_file.exists():
                try:
                    with open(settings_file, "r", encoding="utf-8") as f:
                        settings.update(json.load(f))
                except Exception:
                    pass

            # Cập nhật tên công ty và địa chỉ
            settings["company_name"] = company_name.strip()
            settings["address"] = address.strip()

            # Xử lý file logo tải lên
            if logo_file and logo_file.filename:
                # Lấy phần mở rộng file (định dạng ảnh)
                ext = Path(logo_file.filename).suffix.lower()
                if ext not in [".jpg", ".jpeg", ".png", ".svg", ".webp", ".gif"]:
                    request.session["settings_error"] = "Định dạng ảnh logo không hợp lệ! Vui lòng chọn file ảnh (png, jpg, jpeg, svg...)."
                    return RedirectResponse("/brand-settings", status_code=303)

                # Tạo thư mục static nếu chưa có
                static_dir.mkdir(parents=True, exist_ok=True)
                logo_filename = f"custom_brand_logo{ext}"
                dest_path = static_dir / logo_filename

                # Ghi nội dung file
                with open(dest_path, "wb") as buffer:
                    shutil.copyfileobj(logo_file.file, buffer)

                # Lưu url logo mới
                settings["logo_url"] = f"/static/{logo_filename}"

            # Lưu lại file cấu hình JSON
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            request.session["settings_success"] = "Lưu cấu hình đơn vị sử dụng thành công!"

        except Exception as e:
            request.session["settings_error"] = f"Lỗi khi lưu cấu hình: {e}"

        return RedirectResponse("/brand-settings", status_code=303)

    return router
