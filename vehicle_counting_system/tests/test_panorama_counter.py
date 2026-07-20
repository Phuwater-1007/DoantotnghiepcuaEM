from vehicle_counting_system.counters.panorama_counter import PanoramaCounter
from vehicle_counting_system.models.tracked_object import TrackedObject


def _track(track_id: int, class_name: str, stable_id: int | None = None):
    return TrackedObject(
        track_id=track_id,
        stable_id=stable_id,
        class_id=0,
        class_name=class_name,
        bbox=(0, 0, 20, 20),
        confidence=0.9,
    )


def test_counts_unique_stable_ids_only_after_minimum_frames():
    counter = PanoramaCounter(min_track_frames=3)

    counter.process([_track(10, "car", stable_id=1), _track(20, "motorcycle", stable_id=2)])
    counter.process([_track(10, "car", stable_id=1)])
    stats = counter.process([_track(99, "car", stable_id=1)])

    assert stats.total == 1
    assert stats.per_class == {"motorcycle": 0, "car": 1, "bus": 0, "truck": 0}


def test_short_noisy_tracks_are_not_counted():
    counter = PanoramaCounter(min_track_frames=2)
    stats = counter.process([_track(1, "truck", stable_id=101)])

    assert stats.total == 0
    assert stats.per_class["truck"] == 0


def test_class_is_chosen_by_votes_and_can_stabilize_after_confirmation():
    counter = PanoramaCounter(min_track_frames=3)
    counter.process([_track(1, "bus", stable_id=5)])
    counter.process([_track(1, "truck", stable_id=5)])
    stats = counter.process([_track(1, "bus", stable_id=5)])
    assert stats.per_class["bus"] == 1

    counter.process([_track(1, "truck", stable_id=5)])
    stats = counter.process([_track(1, "truck", stable_id=5)])
    assert stats.total == 1
    assert stats.per_class["bus"] == 0
    assert stats.per_class["truck"] == 1


def test_duplicate_identity_in_same_frame_counts_as_one_observation():
    counter = PanoramaCounter(min_track_frames=2)
    duplicate = [_track(1, "car", stable_id=7), _track(2, "car", stable_id=7)]
    counter.process(duplicate)
    stats = counter.process([_track(3, "car", stable_id=7)])
    assert stats.total == 1
