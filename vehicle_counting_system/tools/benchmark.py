from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import torch

# Allow running as a script from subfolder (tools/).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehicle_counting_system.core.frame_processor import FrameProcessor
from vehicle_counting_system.detectors.yolo_detector import YOLODetector
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker


def main() -> None:
    p = argparse.ArgumentParser(description="Quick FPS/VRAM benchmark (headless).")
    p.add_argument("--video", required=True, help="Path to an input video")
    p.add_argument("--frames", type=int, default=200, help="Number of frames to process")
    args = p.parse_args()

    processor = FrameProcessor(detector=YOLODetector(), tracker=ByteTrackTracker())
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {args.video}")

    n = int(args.frames)
    t0 = time.perf_counter()
    count = 0
    while count < n:
        ok, frame = cap.read()
        if not ok:
            break
        _ = processor.process(frame)
        count += 1
    cap.release()

    elapsed = time.perf_counter() - t0
    fps = count / max(1e-9, elapsed)

    print(f"frames={count} elapsed_s={elapsed:.3f} fps={fps:.2f}")
    if torch.cuda.is_available():
        alloc = torch.cuda.memory_allocated() / 1024 / 1024
        reserved = torch.cuda.memory_reserved() / 1024 / 1024
        print(f"cuda_mem_allocated_mb={alloc:.1f} cuda_mem_reserved_mb={reserved:.1f}")


if __name__ == "__main__":
    main()

