import sys
import os
from pathlib import Path

sys.path.append(os.getcwd())

import vehicle_counting_system.configs.settings as settings_module
from vehicle_counting_system.core.pipeline import Pipeline
def evaluate_tracking(video_file, act, mat, lost, consec):
    settings = settings_module.settings
    settings.bytetrack_activation_threshold = act
    settings.bytetrack_matching_threshold = mat
    settings.bytetrack_lost_buffer = lost
    settings.bytetrack_min_consecutive = consec
    settings.video_sharpen = 0.0
    
    pipeline = Pipeline(
        input_source=f"data/inputs/videos/{video_file}",
        output_path=None,
        export_csv=False
    )
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
    pipeline.state = 1
    
    frame_idx = 0
    while not pipeline._stop_event.is_set():
        ok, frame = pipeline._read_next_frame()
        if not ok: break
        if frame_idx % pipeline.skip_frames == 0:
            pipeline.processor.process(frame)
        frame_idx += 1
    pipeline.cleanup_resources()
    
    return max_id

print("Testing Test3.mp4...")
print("Baseline (0.35, 0.75, 30, 1): Max ID =", evaluate_tracking("Test3.mp4", 0.35, 0.75, 30, 1))
print("Current (0.35, 0.70, 150, 1): Max ID =", evaluate_tracking("Test3.mp4", 0.35, 0.70, 150, 1))
print("Tighter (0.35, 0.65, 150, 1): Max ID =", evaluate_tracking("Test3.mp4", 0.35, 0.65, 150, 1))
