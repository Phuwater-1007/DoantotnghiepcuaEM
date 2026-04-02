"""MJPEG streaming endpoint – stream video file dynamically from MonitoringService."""

from __future__ import annotations

import time
import numpy as np
import cv2
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vehicle_counting_system.presentation.web.dependencies import get_container, get_current_user
from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)


def _make_placeholder_frame(text: str = "Đang kết nối...", width: int = 640, height: int = 360) -> bytes:
    """Tạo 1 frame JPEG placeholder với text, dùng khi chưa có frame thật."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (30, 30, 30)  # dark background
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    thickness = 2
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    x = (width - text_size[0]) // 2
    y = (height + text_size[1]) // 2
    cv2.putText(img, text, (x, y), font, font_scale, (200, 200, 200), thickness, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buf.tobytes()


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["stream"])

    def _require_auth(request: Request):
        user = get_current_user(request)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return None

    # -----------------------------------------------------------------
    # MJPEG stream endpoint
    # -----------------------------------------------------------------
    @router.get("/stream/active")
    @router.get("/stream/{source_id}")
    def stream_video(request: Request, source_id: int | None = None):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err

        container = get_container(request)

        def generate():
            last_frame = None
            # Grace period: chờ tối đa 15s để session bắt đầu và gửi frame đầu tiên
            # Trong khi chờ, gửi placeholder frame mỗi giây để giữ kết nối MJPEG
            max_wait = 15.0
            start_time = time.time()
            got_first_real_frame = False
            placeholder = _make_placeholder_frame("Dang ket noi stream...")
            placeholder_sent = False

            try:
                while True:
                    active_session = container.monitoring_service.get_active_session_id()
                    elapsed = time.time() - start_time

                    # Nếu không có session active
                    if active_session is None:
                        if got_first_real_frame:
                            # Session đã kết thúc sau khi đã stream → dừng
                            break
                        if elapsed > max_wait:
                            # Đã chờ quá lâu mà không có session → dừng
                            break
                        # Gửi placeholder frame để giữ kết nối
                        if not placeholder_sent or int(elapsed) % 2 == 0:
                            yield (
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" +
                                placeholder +
                                b"\r\n"
                            )
                            placeholder_sent = True
                        time.sleep(0.5)
                        continue

                    frame = container.monitoring_service.get_latest_mjpeg_frame()
                    if frame and frame != last_frame:
                        got_first_real_frame = True
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" +
                            frame +
                            b"\r\n"
                        )
                        last_frame = frame
                    else:
                        # Session active nhưng chưa có frame mới
                        if not got_first_real_frame and not placeholder_sent:
                            yield (
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" +
                                placeholder +
                                b"\r\n"
                            )
                            placeholder_sent = True
                        time.sleep(0.02)  # Pacing 50FPS max query

            except GeneratorExit:
                # Trình duyệt ngắt kết nối
                pass
            except Exception:
                logger.exception("Lỗi phát stream MJPEG từ MonitoringService")

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # -----------------------------------------------------------------
    # Giữ endpoint stats đề phòng FE cũ gọi
    # -----------------------------------------------------------------
    @router.get("/stream/{source_id}/stats")
    def stream_stats(request: Request, source_id: int):
        container = get_container(request)
        live_state = container.monitoring_service.get_live_state()
        if not live_state or live_state.get("source_id") != source_id:
            return {"streaming": False, "total": 0, "per_class": {}}
        
        summary = live_state.get("summary", {})
        return {"streaming": True, **summary}

    @router.post("/stream/{source_id}/stop")
    def stop_stream(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        # Dừng luồng phân tích toàn cục
        container = get_container(request)
        container.monitoring_service.stop_active_session()
        return {"ok": True}

    return router
