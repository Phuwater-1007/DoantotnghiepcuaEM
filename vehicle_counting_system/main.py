from __future__ import annotations

import os
import sys
from pathlib import Path

# Cho phép ấn Run trong VS Code: python vehicle_counting_system/main.py
_MAIN_DIR = Path(__file__).resolve().parent
_ROOT = _MAIN_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_MAIN_DIR)

import atexit
import argparse
import signal
import tempfile

from vehicle_counting_system.configs.paths import INPUT_VIDEOS_DIR, OUTPUT_VIDEOS_DIR
from vehicle_counting_system.core.shutdown_manager import finalize_process_exit, log_shutdown_snapshot
from vehicle_counting_system.core.pipeline import Pipeline
from vehicle_counting_system.utils.file_utils import ensure_dir
from vehicle_counting_system.utils.logger import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover - optional helper
    psutil = None


logger = get_logger(__name__)


def _parse_source(value: str):
    # Allow camera index: "0", "1", ...
    if value.isdigit():
        return int(value)
    return value


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Vehicle counting system (detect -> track -> count).")
    p.add_argument(
        "--source",
        default=str(INPUT_VIDEOS_DIR / "test.mp4"),
        help="Video path or camera index (e.g. '0'). Default: data/(input|inputs)/videos/test.mp4",
    )
    p.add_argument(
        "--output-video",
        default=str(OUTPUT_VIDEOS_DIR / "result.mp4"),
        help="Output video path (mp4). Default: data/(output|outputs)/videos/result.mp4",
    )
    p.add_argument(
        "--counting-lines",
        default=None,
        help="Path to counting_lines.json (optional). Default: configs/counting_lines.json",
    )
    p.add_argument(
        "--no-export-csv",
        action="store_true",
        help="Disable exporting summary CSV at the end.",
    )
    return p


def _main_script_path() -> str:
    return str(Path(__file__).resolve()).lower().replace("\\", "/")


def _pid_file_path() -> Path:
    return Path(tempfile.gettempdir()) / "vehicle_counting_system-main.pid"


def _cmdline_matches_app(command_line: str | None) -> bool:
    if not command_line:
        return False
    normalized = command_line.lower().replace("\\", "/")
    return _main_script_path() in normalized


def _is_running_app_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if psutil is None:
        return False

    try:
        proc = psutil.Process(pid)
        return proc.is_running() and _cmdline_matches_app(" ".join(proc.cmdline()))
    except Exception:
        return False


def _claim_single_instance() -> None:
    pid_file = _pid_file_path()
    current_pid = os.getpid()

    stale_pid = None
    try:
        stale_pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        stale_pid = None

    if stale_pid and stale_pid != current_pid and _is_running_app_pid(stale_pid):
        raise RuntimeError(
            f"Another Vehicle Counting instance is already running (pid={stale_pid}). "
            "Close it first, then start a new run."
        )

    pid_file.write_text(str(current_pid), encoding="utf-8")

    def _cleanup_pid_file() -> None:
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(current_pid):
                pid_file.unlink()
        except Exception:
            pass

    atexit.register(_cleanup_pid_file)


def _install_signal_handlers(pipeline: Pipeline):
    signaled_exit_code: list[int | None] = [None]

    def _handle_signal(signum, _frame) -> None:
        signaled_exit_code[0] = 128 + int(signum)
        logger.warning("Received signal %s. Requesting graceful shutdown.", signum)
        pipeline.shutdown_processing()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass

    return lambda: signaled_exit_code[0]


def main() -> int:
    args = build_argparser().parse_args()
    logger.info("Application startup.")

    ensure_dir(INPUT_VIDEOS_DIR)
    ensure_dir(Path(args.output_video))

    source = _parse_source(args.source)
    if isinstance(source, str) and not Path(source).exists():
        print(f"Missing input video: {source}")
        print(f"Put a test video at: {INPUT_VIDEOS_DIR / 'test.mp4'}")
        return 1

    try:
        _claim_single_instance()
    except RuntimeError as exc:
        print(str(exc))
        return 2

    pipeline = Pipeline(
        source,
        args.output_video,
        counting_lines_path=args.counting_lines,
        export_csv=not args.no_export_csv,
    )
    get_signal_exit_code = _install_signal_handlers(pipeline)
    exit_code = 0
    try:
        log_shutdown_snapshot("startup")
        pipeline.run()
        signaled_code = get_signal_exit_code()
        if signaled_code is not None:
            exit_code = signaled_code
    except KeyboardInterrupt:
        pipeline.shutdown_processing()
        exit_code = 130
    except Exception:
        exit_code = 1
        # Keep traceback visible even when shutdown logic force-exits the process.
        logger.exception("Unhandled exception while running pipeline.")
    finally:
        pipeline.close("main finally block")
        log_shutdown_snapshot("after-pipeline-close")
        exit_code = finalize_process_exit(exit_code)
        logger.info("Application shutdown complete with exit_code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

