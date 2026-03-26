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
        return RedirectResponse("/dashboard", status_code=303)
    return user


def base_context(request: Request, **extra: Any) -> dict[str, Any]:
    return {
        "request": request,
        "current_user": get_current_user(request),
        **extra,
    }
