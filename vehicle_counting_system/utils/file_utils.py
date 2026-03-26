from __future__ import annotations

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def ensure_dir(path: PathLike) -> Path:
    """
    Ensure a directory exists and return the directory path.

    If `path` looks like a file path, only the parent directory is created.
    This keeps callers safe when passing output files such as `result.mp4`.
    """
    p = Path(path)
    target_dir = p.parent if p.suffix else p
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def ensure_parent_dir(file_path: PathLike) -> Path:
    """Ensure the parent directory of a file exists."""
    return ensure_dir(Path(file_path).parent)


def list_videos(directory: PathLike) -> list[str]:
    """Return video files inside `directory` sorted by name."""
    root = Path(directory)
    if not root.exists():
        return []
    return sorted(
        str(path)
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def list_videos_recursive(directory: PathLike) -> list[str]:
    """Return video files in directory and subdirectories, sorted by path."""
    root = Path(directory)
    if not root.exists():
        return []
    return sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
