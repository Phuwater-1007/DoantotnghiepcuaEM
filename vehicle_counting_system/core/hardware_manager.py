# ===== file: core/hardware_manager.py =====
"""Manage hardware-related queries such as GPU availability or camera index."""

from __future__ import annotations

from vehicle_counting_system.utils.logger import get_logger
from vehicle_counting_system.configs.settings import settings

logger = get_logger(__name__)


def get_preferred_device() -> str:
    """
    Decide whether to use CUDA or CPU based on settings and torch capability.
    """
    try:
        import torch
    except ImportError:
        logger.warning("torch not installed, forcing CPU.")
        return "cpu"

    if settings.use_gpu and torch.cuda.is_available():
        return settings.device if settings.device.startswith("cuda") else "cuda"
    return "cpu"


def empty_gpu_cache_if_needed() -> None:
    """
    Clear CUDA cache when shutting down, nếu đang dùng GPU.
    Không gọi mỗi frame để tránh overhead.
    """
    try:
        import torch

        if settings.use_gpu and torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
            logger.info("CUDA cache cleared.")
    except ImportError:
        return
