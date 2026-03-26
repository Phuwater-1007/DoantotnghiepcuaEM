from __future__ import annotations

import gc
import multiprocessing
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from vehicle_counting_system.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import psutil
except ImportError:  # pragma: no cover - optional helper
    psutil = None


@dataclass(frozen=True)
class ShutdownSnapshot:
    python_threads: tuple[str, ...]
    child_pids: tuple[int, ...]
    os_thread_count: int | None
    rss_mb: float | None


def run_cleanup_step(
    label: str,
    action: Callable[[], None],
    *,
    timeout: float = 2.0,
) -> bool:
    """
    Execute a cleanup action with visible checkpoints.

    Native library teardown can block forever on Windows/CUDA/OpenCV. Running
    each step in a daemon thread keeps the main shutdown path deterministic.
    """
    logger.info("[>] %s", label)
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            action()
        except BaseException as exc:  # pragma: no cover - defensive
            error.append(exc)

    worker = threading.Thread(
        target=_runner,
        name=f"cleanup:{label}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=max(0.0, timeout))

    if worker.is_alive():
        logger.error("[X] %s timed out after %.1fs", label, timeout)
        return False
    if error:
        logger.exception("[X] %s failed: %s", label, error[0], exc_info=error[0])
        return False

    logger.info("[V] %s", label)
    return True


def capture_shutdown_snapshot() -> ShutdownSnapshot:
    current = threading.current_thread()
    python_threads = tuple(
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive() and thread is not current
    )

    child_pids: set[int] = set()
    try:
        for child in multiprocessing.active_children():
            if child.pid:
                child_pids.add(int(child.pid))
    except Exception:
        pass

    os_thread_count = None
    rss_mb = None
    if psutil is not None:
        try:
            proc = psutil.Process(os.getpid())
            os_thread_count = proc.num_threads()
            rss_mb = proc.memory_info().rss / 1024 / 1024
            for child in proc.children(recursive=True):
                if child.is_running():
                    child_pids.add(int(child.pid))
        except Exception:
            pass

    return ShutdownSnapshot(
        python_threads=python_threads,
        child_pids=tuple(sorted(child_pids)),
        os_thread_count=os_thread_count,
        rss_mb=rss_mb,
    )


def log_shutdown_snapshot(stage: str) -> ShutdownSnapshot:
    snapshot = capture_shutdown_snapshot()
    logger.info(
        "Shutdown snapshot [%s]: python_threads=%s child_pids=%s os_thread_count=%s rss_mb=%s",
        stage,
        list(snapshot.python_threads),
        list(snapshot.child_pids),
        snapshot.os_thread_count,
        None if snapshot.rss_mb is None else round(snapshot.rss_mb, 1),
    )
    return snapshot


def has_lingering_runtime(snapshot: ShutdownSnapshot) -> bool:
    if snapshot.python_threads:
        return True
    if snapshot.child_pids:
        return True
    if snapshot.os_thread_count is not None and snapshot.os_thread_count > 1:
        return True
    return False


def terminate_child_processes(timeout: float = 1.0) -> None:
    if psutil is not None:
        try:
            proc = psutil.Process(os.getpid())
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            gone, alive = psutil.wait_procs(children, timeout=timeout)
            for child in alive:
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        for child in multiprocessing.active_children():
            try:
                child.terminate()
            except Exception:
                pass
            try:
                child.join(timeout=timeout)
            except Exception:
                pass
    except Exception:
        pass


def join_python_threads(timeout: float = 0.5) -> None:
    current = threading.current_thread()
    deadline = time.perf_counter() + max(0.0, timeout)
    for thread in list(threading.enumerate()):
        if thread is current:
            continue
        remaining = max(0.0, deadline - time.perf_counter())
        if remaining <= 0:
            break
        try:
            thread.join(timeout=remaining)
        except Exception:
            pass


def release_runtime_resources() -> None:
    try:
        import cv2

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        for _ in range(5):
            try:
                cv2.waitKey(1)
            except Exception:
                break
            time.sleep(0.01)
    except Exception:
        pass

    try:
        import torch

        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
    except Exception:
        pass

    gc.collect()


def finalize_process_exit(exit_code: int, *, force_timeout: float = 1.5) -> int:
    """
    Try graceful shutdown first. Only force-exit if workers/resources still keep
    the interpreter alive after cleanup and a short grace period.
    """
    release_runtime_resources()
    terminate_child_processes(timeout=0.5)
    join_python_threads(timeout=0.5)
    snapshot = log_shutdown_snapshot("post-cleanup")
    if not has_lingering_runtime(snapshot):
        return exit_code

    deadline = time.perf_counter() + max(0.0, force_timeout)
    while time.perf_counter() < deadline:
        time.sleep(0.1)
        snapshot = capture_shutdown_snapshot()
        if not has_lingering_runtime(snapshot):
            logger.info("Shutdown completed gracefully after grace wait.")
            return exit_code

    logger.warning(
        "Forcing final process exit because runtime is still alive after cleanup: "
        "python_threads=%s child_pids=%s os_thread_count=%s",
        list(snapshot.python_threads),
        list(snapshot.child_pids),
        snapshot.os_thread_count,
    )
    os._exit(exit_code)
