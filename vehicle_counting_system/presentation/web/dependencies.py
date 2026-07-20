from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse

from vehicle_counting_system.configs.paths import DATA_DIR, INPUT_VIDEOS_DIR, OUTPUT_VIDEOS_DIR, PROJECT_ROOT
from vehicle_counting_system.utils.file_utils import list_videos, list_videos_recursive


def list_input_videos() -> list[dict[str, str]]:
    """
    Quét video trong data/input, data/inputs và thư mục con. Bỏ qua thư mục output.
    Trả về {path, name} với path tương đối từ PROJECT_ROOT để dùng làm source_uri.
    """
    videos: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    project_root = Path(PROJECT_ROOT).resolve()
    output_dir = Path(OUTPUT_VIDEOS_DIR).resolve()

    dirs_to_scan = [
        INPUT_VIDEOS_DIR,
        DATA_DIR / "input",
        DATA_DIR / "inputs",
        DATA_DIR / "input" / "videos",
        DATA_DIR / "inputs" / "videos",
        Path(PROJECT_ROOT).parent / "data" / "input",
        Path(PROJECT_ROOT).parent / "data" / "inputs",
    ]

    for base_dir in dirs_to_scan:
        if not base_dir.exists():
            continue
        base_resolved = Path(base_dir).resolve()
        if output_dir in (base_resolved, base_resolved.parent) or str(base_resolved).startswith(str(output_dir)):
            continue
        paths = list_videos_recursive(base_dir)
        for full_path_str in paths:
            full_path = Path(full_path_str).resolve()
            if str(full_path) in seen_paths:
                continue
            try:
                full_path.relative_to(output_dir)
                continue
            except ValueError:
                pass
            seen_paths.add(str(full_path))
            try:
                rel = full_path.relative_to(project_root)
                rel_str = str(rel).replace("\\", "/")
            except ValueError:
                try:
                    rel = full_path.relative_to(project_root.parent)
                    rel_str = "../" + str(rel).replace("\\", "/")
                except ValueError:
                    continue
            videos.append({
                "path": rel_str,
                "name": full_path.name,
                "preview_url": "/api/video/input?path=" + quote(str(rel_str).replace("\\", "/")),
            })

    return sorted(videos, key=lambda v: (v["path"].lower(), v["name"]))


def to_input_preview_url(rel_path: str | None) -> str | None:
    """Build /api/video/input?path=... URL for input video preview."""
    if not rel_path or not rel_path.strip():
        return None
    return "/api/video/input?path=" + quote(rel_path.strip())


def to_media_url(file_path: str | None) -> str | None:
    """Build /media/ URL for output video. Only paths under OUTPUT_VIDEOS_DIR are allowed."""
    if not file_path:
        return None
    path = Path(file_path).resolve()
    try:
        path.relative_to(OUTPUT_VIDEOS_DIR.resolve())
        return "/media/" + path.name
    except ValueError:
        return None


def list_output_videos() -> list[dict[str, str]]:
    """Liệt kê tất cả video trong thư mục output (kể cả result.mp4 từ main.py)."""
    videos = []
    for path_str in list_videos(OUTPUT_VIDEOS_DIR):
        name = Path(path_str).name
        videos.append({"name": name, "media_url": "/media/" + name})
    return sorted(videos, key=lambda v: v["name"], reverse=True)


def get_container(request: Request):
    return request.app.state.container


def get_current_user(request: Request):
    container = get_container(request)
    
    # Require login every time the server is restarted from VS Code
    # by ensuring the session belongs to the current server instance.
    session_instance = request.session.get("instance_id")
    if session_instance != request.app.state.instance_id:
        # Preserve CSRF token so the next POST (e.g. login) still works
        csrf_token = request.session.get("csrf_token")
        request.session.clear()
        if csrf_token:
            request.session["csrf_token"] = csrf_token
        return None
        
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return container.auth_service.get_user(int(user_id))


def require_login(request: Request):
    user = get_current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return user


def require_admin(request: Request):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    if user.role != "admin":
        return RedirectResponse("/access-denied", status_code=303)
    return user


def _ensure_csrf_token(request: Request) -> str:
    """Return CSRF token from session, generating one if missing."""
    import secrets

    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def base_context(request: Request, **extra: Any) -> dict[str, Any]:
    import json
    settings_file = DATA_DIR / "system_settings.json"
    settings = {
        "company_name": "Giám sát Giao thông",
        "subtitle": "Đồ án tốt nghiệp",
        "logo_url": "/static/brand_logo.jpg",
        "address": ""
    }
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings.update(data)
        except Exception:
            pass

    # Cache busting for logo to prevent browser caching old images
    def _add_cache_buster(url_str: str) -> str:
        if url_str and url_str.startswith("/static/"):
            static_dir = Path(__file__).resolve().parent / "static"
            logo_rel_path = url_str[len("/static/"):]
            logo_path = static_dir / logo_rel_path
            if logo_path.exists():
                mtime = int(logo_path.stat().st_mtime)
                base_url = url_str.split("?")[0]
                return f"{base_url}?t={mtime}"
        return url_str

    if settings.get("logo_url"):
        settings["logo_url"] = _add_cache_buster(settings["logo_url"])

    if "settings" in extra and isinstance(extra["settings"], dict) and extra["settings"].get("logo_url"):
        extra["settings"]["logo_url"] = _add_cache_buster(extra["settings"]["logo_url"])

    return {
        "request": request,
        "current_user": get_current_user(request),
        "csrf_token": _ensure_csrf_token(request),
        "system_settings": settings,
        **extra,
    }
