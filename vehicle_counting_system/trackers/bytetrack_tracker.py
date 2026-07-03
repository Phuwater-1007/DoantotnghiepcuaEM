# ===== file: trackers/bytetrack_tracker.py =====
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import supervision as sv

from vehicle_counting_system.configs.settings import settings
from vehicle_counting_system.models.detection import Detection
from vehicle_counting_system.models.tracked_object import TrackedObject
from vehicle_counting_system.trackers.base_tracker import BaseTracker
from vehicle_counting_system.utils.math_utils import iou_xyxy


class ByteTrackTracker(BaseTracker):
    """
    ByteTrack tracker wrapper using `supervision` implementation.

    Tính năng chính (v2 — Re-ID):
    ─────────────────────────────
    1. ByteTrack gốc (qua supervision) để match detection → track bằng Kalman + IoU.
    2. **IoU Re-ID**: Khi ByteTrack tạo track mới, kiểm tra với bộ nhớ "recently lost" —
       nếu IoU đủ cao → kế thừa history, display_id, stable_id từ track cũ.
       → Giải quyết triệt để hiện tượng ID nhấp nháy (1 xe nhảy từ ID 1→13).
    3. Stable ID mapping: mỗi xe có 1 stable_id duy nhất, không thay đổi dù ByteTrack
       internal ID có thay đổi bao nhiêu lần.

    Goals for graduation demo:
    - Stable IDs under occlusion / dense traffic
    - Lightweight enough for RTX 3050
    - Minimal integration changes (keep detect -> track -> count pipeline)
    """

    # IoU threshold để quyết định 2 bbox là "cùng 1 xe"
    _REID_IOU_THRESHOLD = 0.20
    # Số frame giữ track đã mất trong bộ nhớ Re-ID (cao hơn = nhớ lâu hơn,
    # nhưng tăng risk false Re-ID ở ngã tư đông)
    _REID_MEMORY_FRAMES = 60

    def __init__(self, frame_rate: int = 30):
        self._init_state(frame_rate)

    def _init_state(self, frame_rate: int = 30) -> None:
        self._frame_idx = 0
        self._next_display_id = 1
        self._next_stable_id = 1
        self._bt = sv.ByteTrack(
            track_activation_threshold=settings.bytetrack_activation_threshold,
            lost_track_buffer=settings.bytetrack_lost_buffer,
            minimum_matching_threshold=settings.bytetrack_matching_threshold,
            # Sử dụng frame_rate động đo được từ video để đảm bảo Kalman Filter hoạt động chính xác
            frame_rate=frame_rate,
            minimum_consecutive_frames=settings.bytetrack_min_consecutive,
        )
        # Active tracks: track_id → TrackedObject
        self._tracks: Dict[int, TrackedObject] = {}
        self._last_seen: Dict[int, int] = {}

        # === Re-ID Memory ===
        # Khi track bị prune (mất), lưu lại bbox + metadata để match với track mới.
        # Structure: list of (frame_lost, bbox, history, display_id, stable_id, class_name)
        self._recently_lost: List[_LostTrack] = []

        # Map stable_id → track_id hiện tại (để counter có thể dùng stable_id)
        self._stable_to_track: Dict[int, int] = {}

    def reset(self) -> None:
        # supervision ByteTrack has its own internal state; easiest & safest is recreate it.
        self._init_state()

    def update(self, detections: List[Detection]) -> List[TrackedObject]:
        self._frame_idx += 1

        if not detections:
            # Prune stale tracks (avoid memory growth).
            self._prune_stale()
            return []

        xyxy = np.array([d.bbox for d in detections], dtype=np.float32)
        conf = np.array([d.confidence for d in detections], dtype=np.float32)
        cls = np.array([d.class_id for d in detections], dtype=np.int32)
        # Best-effort map from class_id to class_name from detector output.
        cls_name_map: Dict[int, str] = {}
        for d in detections:
            cls_name_map.setdefault(int(d.class_id), d.class_name)

        dets = sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls)
        tracked = self._bt.update_with_detections(dets)

        out: List[TrackedObject] = []
        if tracked.tracker_id is None or len(tracked) == 0:
            self._prune_stale()
            return out

        # Lấy danh sách các track ID đang active trong frame hiện tại
        active_tids = {int(tid) for tid in tracked.tracker_id}

        # Map back to our TrackedObject (keep anchor history).
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            bbox = tuple(map(float, tracked.xyxy[i]))
            confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            class_id = int(tracked.class_id[i]) if tracked.class_id is not None else -1

            class_name = cls_name_map.get(class_id, str(class_id))

            if tid in self._tracks:
                # ── Track đã tồn tại → cập nhật bình thường ──
                obj = self._tracks[tid]
                obj.update(bbox, class_id=class_id, class_name=class_name, confidence=confidence)
            else:
                # ── Track MỚI từ ByteTrack → thử Re-ID với các track không active (inactive) trong self._tracks ──
                matched_tid, matched_obj = self._find_reid_match(bbox, class_name, active_tids)

                if matched_obj is not None and matched_tid is not None:
                    # Re-ID thành công! Kế thừa toàn bộ từ track cũ.
                    obj = TrackedObject(
                        track_id=tid,
                        class_id=class_id,
                        class_name=class_name,
                        bbox=bbox,
                        confidence=confidence,
                        history=matched_obj.history.copy(),  # Kế thừa trajectory
                        display_id=matched_obj.display_id,   # Giữ display ID cũ
                        stable_id=matched_obj.stable_id,     # Giữ stable ID cũ
                    )
                    obj.update(bbox, class_id=class_id, class_name=class_name, confidence=confidence)

                    # Xóa track cũ khỏi self._tracks để tránh trùng lặp
                    self._tracks.pop(matched_tid, None)
                    self._last_seen.pop(matched_tid, None)

                    # Cập nhật stable mapping
                    if obj.stable_id is not None:
                        self._stable_to_track[obj.stable_id] = tid
                else:
                    # Track hoàn toàn mới (xe mới xuất hiện)
                    new_stable_id = self._next_stable_id
                    self._next_stable_id += 1

                    obj = TrackedObject(
                        track_id=tid,
                        class_id=class_id,
                        class_name=class_name,
                        bbox=bbox,
                        confidence=confidence,
                        history=[],
                        display_id=None,  # Sẽ gán khi vào ROI
                        stable_id=new_stable_id,
                    )
                    obj.update(bbox, class_id=class_id, class_name=class_name, confidence=confidence)
                    self._stable_to_track[new_stable_id] = tid

                self._tracks[tid] = obj

            self._last_seen[tid] = self._frame_idx
            out.append(obj)

        self._prune_stale()
        return out

    def _find_reid_match(self, new_bbox: tuple, new_class: str, active_tids: set[int]) -> Tuple[int | None, TrackedObject | None]:
        """
        Tìm kiếm trong các track không active (inactive) xem có track nào match với xe mới không.
        Sử dụng kết hợp IoU và khoảng cách tâm (hỗ trợ khi xe chạy nhanh/FPS thấp).
        """
        best_tid = None
        best_obj = None
        best_score = 0.0

        # Tọa độ tâm của bbox mới
        c_new_x = (new_bbox[0] + new_bbox[2]) / 2.0
        c_new_y = (new_bbox[1] + new_bbox[3]) / 2.0

        for tid, obj in self._tracks.items():
            if tid in active_tids:
                continue
            if obj.class_name != new_class:
                continue

            last_seen_frame = self._last_seen.get(tid, 0)
            age = self._frame_idx - last_seen_frame
            # Chỉ cho phép Re-ID trong vòng _REID_MEMORY_FRAMES
            if age > self._REID_MEMORY_FRAMES:
                continue

            # 1. Thử match bằng IoU
            overlap = iou_xyxy(new_bbox, obj.bbox)
            if overlap >= self._REID_IOU_THRESHOLD:
                # Ưu tiên IoU: gán score = 1.0 + overlap để chắc chắn lớn hơn score khoảng cách
                score = 1.0 + overlap
                if score > best_score:
                    best_score = score
                    best_tid = tid
                    best_obj = obj
            else:
                # 2. Thử match bằng khoảng cách tâm nếu IoU bằng 0 hoặc thấp (xe di chuyển xa giữa các frame)
                c_old_x = (obj.bbox[0] + obj.bbox[2]) / 2.0
                c_old_y = (obj.bbox[1] + obj.bbox[3]) / 2.0

                dist = ((c_new_x - c_old_x) ** 2 + (c_new_y - c_old_y) ** 2) ** 0.5

                w_new = new_bbox[2] - new_bbox[0]
                h_new = new_bbox[3] - new_bbox[1]
                area_new = w_new * h_new

                w_old = obj.bbox[2] - obj.bbox[0]
                h_old = obj.bbox[3] - obj.bbox[1]
                area_old = w_old * h_old

                if area_new > 0 and area_old > 0:
                    area_ratio = area_new / area_old if area_new > area_old else area_old / area_new
                    size_ok = area_ratio < 2.5  # Kích thước không lệch quá 2.5 lần
                else:
                    size_ok = False

                # Đảm bảo bán kính tìm kiếm tối thiểu (đặc biệt cho xe máy nhỏ phóng nhanh hoặc bị khuất sau xe tải)
                mult = 3.0 if new_class in {"motorcycle", "bicycle"} else 4.0
                max_dist = max(220.0, max(w_new, h_new) * mult)
                if dist < max_dist and size_ok:
                    score = 1.0 - (dist / max_dist)  # Giá trị từ 0.0 -> 1.0
                    if score > best_score:
                        best_score = score
                        best_tid = tid
                        best_obj = obj

        if best_tid is not None:
            return best_tid, best_obj

        # 3. Fallback: Nếu không tìm thấy trong self._tracks, kiểm tra thêm trong _recently_lost (những track đã bị prune)
        best_idx = -1
        best_lost_score = 0.0
        for idx, lost in enumerate(self._recently_lost):
            if lost.class_name != new_class:
                continue

            age = self._frame_idx - lost.frame_lost
            if age > self._REID_MEMORY_FRAMES:
                continue

            overlap = iou_xyxy(new_bbox, lost.bbox)
            if overlap >= self._REID_IOU_THRESHOLD:
                score = 1.0 + overlap
                if score > best_lost_score:
                    best_lost_score = score
                    best_idx = idx
            else:
                c_old_x = (lost.bbox[0] + lost.bbox[2]) / 2.0
                c_old_y = (lost.bbox[1] + lost.bbox[3]) / 2.0
                dist = ((c_new_x - c_old_x) ** 2 + (c_new_y - c_old_y) ** 2) ** 0.5

                w_new = new_bbox[2] - new_bbox[0]
                h_new = new_bbox[3] - new_bbox[1]
                area_new = w_new * h_new

                w_old = lost.bbox[2] - lost.bbox[0]
                h_old = lost.bbox[3] - lost.bbox[1]
                area_old = w_old * h_old

                if area_new > 0 and area_old > 0:
                    area_ratio = area_new / area_old if area_new > area_old else area_old / area_new
                    size_ok = area_ratio < 2.5
                else:
                    size_ok = False

                # Sử dụng hệ số tĩnh tối ưu lớn hơn với bán kính tìm kiếm tối thiểu
                mult = 2.5 if new_class in {"motorcycle", "bicycle"} else 3.5
                max_dist = max(220.0, max(w_new, h_new) * mult)
                if dist < max_dist and size_ok:
                    score = 1.0 - (dist / max_dist)
                    if score > best_lost_score:
                        best_lost_score = score
                        best_idx = idx

        if best_idx >= 0:
            recovered = self._recently_lost.pop(best_idx)
            # Tạo một object giả lập đại diện cho track đã prune
            dummy_obj = TrackedObject(
                track_id=-1,
                class_id=-1,
                class_name=recovered.class_name,
                bbox=recovered.bbox,
                confidence=0.0,
                history=recovered.history,
                display_id=recovered.display_id,
                stable_id=recovered.stable_id,
            )
            return -1, dummy_obj

        return None, None

    def get_or_assign_display_id(self, track_id: int) -> int | None:
        """Gán display_id tăng dần (1, 2, 3...) khi xe đi vào vùng ROI."""
        if track_id not in self._tracks:
            return None
        obj = self._tracks[track_id]
        if obj.display_id is None:
            obj.display_id = self._next_display_id
            self._next_display_id += 1
        return obj.display_id

    def get_stable_id(self, track_id: int) -> int | None:
        """Lấy stable_id của track. Stable ID không đổi dù ByteTrack đổi track_id."""
        if track_id not in self._tracks:
            return None
        return self._tracks[track_id].stable_id

    def _prune_stale(self) -> None:
        """Remove tracks not seen longer than lost buffer (with small margin).
        
        Tracks bị prune sẽ được lưu vào _recently_lost để hỗ trợ Re-ID.
        """
        stale_after = settings.bytetrack_lost_buffer + 5
        stale_ids = [
            tid for tid, last in self._last_seen.items() if (self._frame_idx - last) > stale_after
        ]
        for tid in stale_ids:
            self._last_seen.pop(tid, None)
            old_track = self._tracks.pop(tid, None)

            # Lưu vào bộ nhớ Re-ID nếu track có history đáng kể
            if old_track is not None and len(old_track.history) >= 2:
                self._recently_lost.append(_LostTrack(
                    frame_lost=self._frame_idx,
                    bbox=old_track.bbox,
                    history=old_track.history[-30:],  # Giữ 30 anchor gần nhất
                    display_id=old_track.display_id,
                    stable_id=old_track.stable_id,
                    class_name=old_track.class_name,
                ))

        # Dọn _recently_lost quá hạn
        cutoff = self._frame_idx - self._REID_MEMORY_FRAMES
        self._recently_lost = [lt for lt in self._recently_lost if lt.frame_lost > cutoff]


class _LostTrack:
    """Thông tin tối thiểu của track đã mất, dùng cho Re-ID."""
    __slots__ = ("frame_lost", "bbox", "history", "display_id", "stable_id", "class_name")

    def __init__(
        self,
        frame_lost: int,
        bbox: tuple,
        history: list,
        display_id: int | None,
        stable_id: int | None,
        class_name: str,
    ):
        self.frame_lost = frame_lost
        self.bbox = bbox
        self.history = history
        self.display_id = display_id
        self.stable_id = stable_id
        self.class_name = class_name