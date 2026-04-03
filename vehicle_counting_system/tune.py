import sys
import os
import cv2
from pathlib import Path

# Add current dir to sys.path so we can import modules
sys.path.append(os.getcwd())

import vehicle_counting_system.configs.settings as settings_module
from vehicle_counting_system.core.pipeline import Pipeline
from vehicle_counting_system.detectors.yolo_detector import YOLODetector
from vehicle_counting_system.trackers.bytetrack_tracker import ByteTrackTracker

# Tắt bớt log
from loguru import logger
logger.remove()

def get_max_track_id(act, mat, lost, consec):
    settings = settings_module.settings
    settings.bytetrack_activation_threshold = act
    settings.bytetrack_matching_threshold = mat
    settings.bytetrack_lost_buffer = lost
    settings.bytetrack_min_consecutive = consec
    settings.video_sharpen = 0.0 # Make it faster
    
    pipeline = Pipeline(
        input_source="data/inputs/videos/Test.mp4",
        output_path=None,
        export_csv=False
    )
    # Headless
    pipeline.window_name = "test"
    pipeline._open_window = lambda: None
    pipeline._present_frame = lambda f: True
    pipeline._poll_ui_events = lambda d: False
    
    pipeline._open_source()
    original_process = pipeline.processor._run_inference
    max_id = 0
    def wrapped_inference(frame):
        nonlocal max_id
        tracks, stats = original_process(frame)
        for t in tracks:
            if t.track_id > max_id:
                max_id = t.track_id
        return tracks, stats
    pipeline.processor._run_inference = wrapped_inference
    pipeline.state = 1 # Running state
    
    # Manually run the loop
    fps, delay = pipeline._compute_frame_delay(pipeline._cap)
    frame_idx = 0
    while not pipeline._stop_event.is_set():
        ok, frame = pipeline._read_next_frame()
        if not ok: break
        if frame_idx % pipeline.skip_frames == 0:
            pipeline.processor.process(frame)
        frame_idx += 1
    
    pipeline.cleanup_resources()
    
    num_counted = pipeline.processor.last_stats.total if pipeline.processor and pipeline.processor.last_stats else 0
    print(f"[TEST] ({act:0.2f}, {mat:0.2f}, {lost:3d}, {consec:1d}) => Max ID: {max_id}, Counted: {num_counted}")

print("Running baseline...")
get_max_track_id(0.35, 0.70, 120, 2)
get_max_track_id(0.40, 0.65, 120, 3)
get_max_track_id(0.45, 0.60, 150, 3)
