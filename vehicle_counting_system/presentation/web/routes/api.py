"""REST API JSON endpoints - dữ liệu đếm, sessions, reports, dashboard."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import cv2
from fastapi import APIRouter, Body, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from vehicle_counting_system.configs.paths import DATA_DIR, INPUT_VIDEOS_DIR, PROJECT_ROOT
from vehicle_counting_system.presentation.web.dependencies import get_container, get_current_user, to_media_url
from vehicle_counting_system.utils.file_utils import VIDEO_EXTENSIONS, ensure_dir


class SaveConfigBody(BaseModel):
    roi: list[list[float]]
    line: dict
    width: float = 0
    height: float = 0


class StartWithVideoBody(BaseModel):
    source_id: int | None = None
    video_path: str | None = None


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["api"])

    def _require_auth(request: Request):
        user = get_current_user(request)
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "message": "Đăng nhập để truy cập API"},
            )
        return None

    @router.post("/client/heartbeat")
    def api_client_heartbeat(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        presence = getattr(request.app.state, "client_presence", None)
        if presence is None:
            return {"ok": True, "enabled": False}
        snap = presence.heartbeat()
        return {"ok": True, "enabled": True, "active_tabs": snap.active_tabs, "last_seen_ts": snap.last_seen_ts}

    @router.post("/client/disconnect")
    def api_client_disconnect(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        presence = getattr(request.app.state, "client_presence", None)
        if presence is None:
            return {"ok": True, "enabled": False}
        snap = presence.tab_closed()
        # NOTE: do not shutdown immediately here because `pagehide` also fires on
        # in-tab navigation. Shutdown is handled by web_main.py using a short grace window.
        return {"ok": True, "enabled": True, "active_tabs": snap.active_tabs, "last_seen_ts": snap.last_seen_ts}

    @router.get("/dashboard")
    def api_dashboard(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        data = container.dashboard_service.get_dashboard_data()
        return data

    @router.get("/sessions")
    def api_sessions(request: Request, limit: int = 50):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        rows = container.db.fetchall(
            """
            SELECT sess.id, sess.source_id, sess.status, sess.started_at, sess.finished_at,
                   sess.summary_json, sess.output_video_path, sess.error_message,
                   src.name AS source_name, src.source_type
            FROM analysis_sessions sess
            JOIN sources src ON src.id = sess.source_id
            ORDER BY sess.id DESC
            LIMIT ?
            """,
            (min(limit, 200),),
        )
        import json
        sessions = []
        for row in rows:
            sessions.append({
                "id": int(row["id"]),
                "source_id": int(row["source_id"]),
                "source_name": str(row["source_name"]),
                "source_type": str(row["source_type"]),
                "status": str(row["status"]),
                "started_at": str(row["started_at"]),
                "finished_at": row["finished_at"],
                "summary": json.loads(row["summary_json"] or "{}"),
                "output_video_path": row["output_video_path"],
                "media_url": to_media_url(row["output_video_path"]),
                "error_message": row["error_message"],
            })
        return {"sessions": sessions}

    @router.get("/sessions/{session_id}")
    def api_session_detail(request: Request, session_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        row = container.db.fetchone(
            """
            SELECT sess.id, sess.source_id, sess.status, sess.started_at, sess.finished_at,
                   sess.summary_json, sess.output_video_path, sess.error_message,
                   src.name AS source_name, src.source_type
            FROM analysis_sessions sess
            JOIN sources src ON src.id = sess.source_id
            WHERE sess.id = ?
            """,
            (session_id,),
        )
        if not row:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        import json
        return {
            "id": int(row["id"]),
            "source_id": int(row["source_id"]),
            "source_name": str(row["source_name"]),
            "source_type": str(row["source_type"]),
            "status": str(row["status"]),
            "started_at": str(row["started_at"]),
            "finished_at": row["finished_at"],
            "summary": json.loads(row["summary_json"] or "{}"),
            "output_video_path": row["output_video_path"],
            "media_url": to_media_url(row["output_video_path"]),
            "error_message": row["error_message"],
        }

    @router.get("/reports")
    def api_reports(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        reports = container.report_service.list_reports()
        return {"reports": reports}

    @router.post("/sources/upload")
    async def api_upload_video(request: Request, file: UploadFile = File(...)):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        if not file.filename:
            return JSONResponse(status_code=400, content={"error": "Không có tên file"})
        ext = Path(file.filename).suffix.lower()
        if ext not in VIDEO_EXTENSIONS:
            return JSONResponse(status_code=400, content={"error": f"Định dạng không hỗ trợ. Cho phép: {', '.join(sorted(VIDEO_EXTENSIONS))}"})
        ensure_dir(INPUT_VIDEOS_DIR)

        # Auto-rename on conflict: video.mp4 → video_1.mp4 → video_2.mp4 ...
        stem = Path(file.filename).stem
        dest = INPUT_VIDEOS_DIR / file.filename
        counter = 0
        while dest.exists():
            counter += 1
            dest = INPUT_VIDEOS_DIR / f"{stem}_{counter}{ext}"

        try:
            with open(dest, "wb") as f:
                shutil.copyfileobj(file.file, f)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        rel = dest.relative_to(PROJECT_ROOT)
        rel_str = str(rel).replace("\\", "/")
        container = get_container(request)
        existing = container.source_service.get_source_by_uri(rel_str)
        if existing:
            return {"ok": True, "path": rel_str, "source_id": existing.id, "renamed": counter > 0, "final_name": dest.name}
        name = dest.stem
        try:
            container.source_service.create_source(
                name=name,
                source_type="video",
                source_uri=rel_str,
                notes="Upload từ web",
            )
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        row = container.db.fetchone("SELECT id FROM sources ORDER BY id DESC LIMIT 1")
        source_id = int(row["id"]) if row else None
        return {"ok": True, "path": rel_str, "source_id": source_id, "renamed": counter > 0, "final_name": dest.name}

    @router.get("/video/input")
    def api_input_video(request: Request, path: str = ""):
        """Stream input video for preview. path = relative from PROJECT_ROOT (e.g. data/inputs/videos/x.mp4)."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        if not path or not path.strip():
            return JSONResponse(status_code=400, content={"error": "Thiếu path"})
        p = (PROJECT_ROOT / path.strip().replace("..", "")).resolve()
        allowed_dirs = [
            INPUT_VIDEOS_DIR.resolve(),
            (DATA_DIR / "input").resolve(),
            (DATA_DIR / "inputs").resolve(),
        ]
        if not p.exists() or not p.is_file():
            return JSONResponse(status_code=404, content={"error": "File không tồn tại"})
        in_allowed = False
        for d in allowed_dirs:
            if d.exists():
                try:
                    p.relative_to(d)
                    in_allowed = True
                    break
                except ValueError:
                    pass
        if not in_allowed:
            return JSONResponse(status_code=403, content={"error": "Path không thuộc thư mục input"})
        return FileResponse(str(p), media_type="video/mp4")

    @router.get("/sources")
    def api_sources(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        sources = container.source_service.list_sources()
        return {
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "source_type": s.source_type,
                    "source_uri": s.source_uri,
                    "is_active": s.is_active,
                    "status": s.status,
                    "notes": s.notes,
                    "counting_config_path": s.counting_config_path,
                }
                for s in sources
            ]
        }

    @router.get("/sources/{source_id}/preview-frame")
    def api_source_preview_frame(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source not found"})
        if source.source_type != "video":
            return JSONResponse(status_code=400, content={"error": "Chỉ hỗ trợ video"})
        cap = cv2.VideoCapture(source.source_uri)
        if not cap.isOpened():
            return JSONResponse(status_code=400, content={"error": "Không mở được video"})
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return JSONResponse(status_code=400, content={"error": "Không đọc được frame"})
        _, buf = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return {"image": f"data:image/jpeg;base64,{b64}", "width": frame.shape[1], "height": frame.shape[0]}

    @router.get("/sources/{source_id}/config")
    def api_source_get_config(request: Request, source_id: int):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source not found"})

        from vehicle_counting_system.application.services.source_config_service import load_source_config

        config = load_source_config(source_id)
        line = None
        if config and config.get("lines"):
            line = config["lines"][0]
        return {
            "ok": True,
            "has_config": bool(config),
            "coordinates_mode": (config or {}).get("coordinates_mode", "normalized"),
            "roi": (config or {}).get("roi", []),
            "line": line,
            "config_path": source.counting_config_path,
        }

    @router.post("/sources/{source_id}/config")
    def api_source_save_config(request: Request, source_id: int, body: SaveConfigBody = Body(...)):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source not found"})
        from vehicle_counting_system.application.services.source_config_service import save_source_config

        w, h = float(body.width or 0), float(body.height or 0)
        if w <= 0 or h <= 0:
            return JSONResponse(status_code=400, content={"error": "Thiếu width/height của frame"})

        roi_px = body.roi
        line_px = body.line
        start = line_px.get("start", [0, 0])
        end = line_px.get("end", [0, 0])

        roi_norm = [[float(p[0]) / w, float(p[1]) / h] for p in roi_px]
        line_norm = {
            "id": line_px.get("id", "main_road_downstream"),
            "start": [float(start[0]) / w, float(start[1]) / h],
            "end": [float(end[0]) / w, float(end[1]) / h],
            "direction": "both",
        }

        # --- Server-side ROI/line validation (matches runtime requirements) ---
        if len(roi_norm) < 3:
            return JSONResponse(status_code=400, content={"error": "ROI phải có ít nhất 3 điểm."})
        for i, pt in enumerate(roi_norm):
            if not (0 <= pt[0] <= 1 and 0 <= pt[1] <= 1):
                return JSONResponse(status_code=400, content={"error": f"Điểm ROI #{i+1} nằm ngoài khung hình."})

        ls, le = line_norm["start"], line_norm["end"]
        if not (0 <= ls[0] <= 1 and 0 <= ls[1] <= 1 and 0 <= le[0] <= 1 and 0 <= le[1] <= 1):
            return JSONResponse(status_code=400, content={"error": "Đường đếm nằm ngoài khung hình."})
        if abs(ls[0] - le[0]) < 1e-6 and abs(ls[1] - le[1]) < 1e-6:
            return JSONResponse(status_code=400, content={"error": "Điểm đầu và cuối đường đếm trùng nhau."})

        try:
            path = save_source_config(source_id, roi_norm, line_norm)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        container.source_service.update_counting_config(source_id, path)
        return {"ok": True, "path": path}

    @router.post("/monitoring/start-with-video")
    def api_monitoring_start_with_video(request: Request, body: StartWithVideoBody = Body(...)):
        """Bắt đầu phân tích headless (không hiện cửa sổ video). Dùng ROI đã lưu trên web."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        user = get_current_user(request)
        if user is None:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        container = get_container(request)
        source_id = body.source_id
        if source_id is None:
            return JSONResponse(status_code=400, content={"error": "Thiếu source_id"})
        source = container.source_service.get_source(source_id)
        if not source:
            return JSONResponse(status_code=404, content={"error": "Source không tồn tại"})
        if container.monitoring_service.get_active_session_id() is not None:
            return JSONResponse(status_code=409, content={"error": "Đang có phiên phân tích chạy, vui lòng đợi hoặc dừng"})
        try:
            session_id = container.monitoring_service.start_session(source_id, user_id=user.id)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"ok": True, "session_id": session_id, "source_id": source_id, "source_name": source.name}

    @router.post("/monitoring/stop")
    def api_monitoring_stop(request: Request):
        """Dừng phiên phân tích đang chạy."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        if container.monitoring_service.get_active_session_id() is None:
            return {"ok": True, "message": "Không có phiên đang chạy"}
        container.monitoring_service.stop_active_session()
        return {"ok": True, "message": "Đã dừng phân tích"}

    @router.get("/monitoring/status")
    def api_monitoring_status(request: Request):
        """Trả về trạng thái phiên hiện tại – dùng cho auto-poll từ frontend."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        active_id = container.monitoring_service.get_active_session_id()
        return {"active_session_id": active_id}

    @router.get("/monitoring/live-state")
    def api_monitoring_live_state(request: Request):
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        container = get_container(request)
        active_id = container.monitoring_service.get_active_session_id()
        live_state = container.monitoring_service.get_live_state()
        return {
            "active_session_id": active_id,
            "live_state": live_state,
        }

    @router.get("/monitoring/job-status")
    def api_job_status(request: Request, video_name: str = ""):
        """Trạng thái xử lý: waiting / running / complete / error. video_name = stem (vd: Test3)."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        from pathlib import Path

        from vehicle_counting_system.configs.paths import OUTPUT_VIDEOS_DIR

        stem = video_name.strip() or "result"
        stem = Path(stem).stem
        running_marker = OUTPUT_VIDEOS_DIR / f"{stem}.running"
        output_video = OUTPUT_VIDEOS_DIR / f"{stem}_result.mp4"
        fallback_video = OUTPUT_VIDEOS_DIR / "result.mp4"

        if running_marker.exists():
            return {"status": "running", "source": running_marker.read_text(encoding="utf-8").strip() or stem}
        if output_video.exists():
            return {"status": "complete", "source": stem}
        if stem == "result" and fallback_video.exists():
            return {"status": "complete", "source": "result"}
        return {"status": "waiting", "source": stem}

    @router.get("/monitoring/output-videos")
    def api_output_videos(request: Request):
        """Liệt kê tất cả video đã xử lý (result.mp4, *_result.mp4) kèm summary nếu có."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        import json
        from pathlib import Path

        from vehicle_counting_system.configs.paths import OUTPUT_CSV_DIR, OUTPUT_VIDEOS_DIR
        from vehicle_counting_system.utils.file_utils import list_videos

        videos = []
        for path_str in list_videos(OUTPUT_VIDEOS_DIR):
            path = Path(path_str)
            name = path.name
            if not (name == "result.mp4" or name.endswith("_result.mp4")):
                continue
            stem = path.stem.replace("_result", "") if "_result" in path.stem else "result"
            display_name = stem if stem != "result" else "Kết quả gần nhất"
            summary = None
            summary_path = OUTPUT_VIDEOS_DIR / f"{stem}_summary.json"
            if summary_path.exists():
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if summary is None and name == "result.mp4":
                csv_path = OUTPUT_CSV_DIR / "summary.json"
                if csv_path.exists():
                    try:
                        data = json.loads(csv_path.read_text(encoding="utf-8"))
                        if isinstance(data, list) and data:
                            summary = data[-1]
                    except Exception:
                        pass
            media_url = to_media_url(str(path)) or f"/media/{name}"
            videos.append({
                "name": name,
                "display_name": display_name,
                "url": media_url,
                "summary": summary or {"total": 0, "per_class": {}},
            })
        return {"videos": sorted(videos, key=lambda v: v["name"], reverse=True)}

    @router.get("/monitoring/vscode-output")
    def api_vscode_output(request: Request, video_name: str = ""):
        """Lấy video output + summary từ VS Code (run_with_web_roi.py). video_name = tên file không extension (vd: Test3)."""
        auth_err = _require_auth(request)
        if auth_err is not None:
            return auth_err
        import json
        from pathlib import Path

        from vehicle_counting_system.configs.paths import OUTPUT_CSV_DIR, OUTPUT_VIDEOS_DIR

        if not video_name or not video_name.strip():
            return JSONResponse(status_code=400, content={"error": "Thiếu video_name"})
        stem = Path(video_name.strip()).stem
        video_path = OUTPUT_VIDEOS_DIR / f"{stem}_result.mp4"
        summary_path = OUTPUT_VIDEOS_DIR / f"{stem}_summary.json"

        # Fallback: result.mp4 + last entry từ summary.json (tương thích phiên bản cũ)
        if not video_path.exists():
            fallback_video = OUTPUT_VIDEOS_DIR / "result.mp4"
            if not fallback_video.exists():
                return {"has_output": False, "video_url": None, "summary": None}
            video_path = fallback_video
            summary = None
            csv_summary = OUTPUT_CSV_DIR / "summary.json"
            if csv_summary.exists():
                try:
                    data = json.loads(csv_summary.read_text(encoding="utf-8"))
                    if isinstance(data, list) and data:
                        summary = data[-1]
                except Exception:
                    pass
        else:
            summary = None
            if summary_path.exists():
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        media_url = to_media_url(str(video_path))
        if not media_url:
            media_url = f"/media/{video_path.name}"

        return {
            "has_output": True,
            "video_url": media_url,
            "summary": summary or {"total": 0, "per_class": {}},
        }

    return router
