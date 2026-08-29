import cv2
import numpy as np

from src.services.detect_and_blur import (
    adaptive_kernel_size,
    advance_tracks,
    blur_region,
    redaction_detection_interval,
)


def test_redaction_detection_interval_caps_expensive_inference_without_changing_output_fps() -> None:
    assert redaction_detection_interval(15, 5) == 3
    assert redaction_detection_interval(24, 5) == 5
    assert redaction_detection_interval(1, 5) == 1


def test_tracks_survive_the_gap_between_strided_detections():
    """A stride wider than the persistence window must not expire live tracks.

    ``redact_video`` widens ``max_missed`` to the detection stride for exactly
    this reason: with the bare 0.15s persistence window a 20fps source at 5
    detections/s would drop every box between inferences and flicker the blur.
    """
    stride = redaction_detection_interval(20, 5)
    persist_frames = max(1, round(0.15 * 20))
    max_missed = max(persist_frames, stride)
    assert stride == 4 and persist_frames == 3

    tracks = advance_tracks(
        [],
        [np.array([10, 10, 20, 20])],
        1,
        max_missed=max_missed,
        match_distance=50,
        width=100,
        height=100,
    )
    # Frames 2..4 run no detector; the track has to coast, not expire.
    for frame_idx in range(2, 1 + stride):
        tracks = advance_tracks(
            tracks,
            [],
            frame_idx,
            max_missed=max_missed,
            match_distance=50,
            width=100,
            height=100,
        )
        assert tracks, f"track expired at frame {frame_idx}, before the next detection"

    # The next detection lands and re-anchors the track.
    tracks = advance_tracks(
        tracks,
        [np.array([12, 10, 22, 20])],
        1 + stride,
        max_missed=max_missed,
        match_distance=50,
        width=100,
        height=100,
    )
    assert tracks[0]["box"].tolist() == [12.0, 10.0, 22.0, 20.0]


#


def test_adaptive_kernel_is_odd_bounded_and_scales_with_roi():
    small = adaptive_kernel_size(20, 10, 0.75, 15, 151)
    large = adaptive_kernel_size(200, 100, 0.75, 15, 151)

    assert small == 15
    assert large > small
    assert small % 2 == 1
    assert large % 2 == 1
    assert large <= 151
    assert adaptive_kernel_size(200, 200, 1.0, 15, 100) == 99


def test_blur_region_uses_adaptive_kernel_and_only_touches_roi(monkeypatch):
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    frame[:, :] = 255
    calls = []

    def fake_gaussian_blur(roi, kernel, sigma):
        calls.append((roi.shape, kernel, sigma))
        return np.zeros_like(roi)

    monkeypatch.setattr(cv2, "GaussianBlur", fake_gaussian_blur)
    blur_region(
        frame,
        10,
        10,
        30,
        20,
        kernel_ratio=0.75,
        min_kernel=15,
        max_kernel=151,
    )

    assert calls == [((10, 20, 3), (15, 15), 0)]
    assert np.all(frame[:10] == 255)
    assert np.all(frame[20:] == 255)
    assert np.all(frame[:, :10] == 255)
    assert np.all(frame[:, 30:] == 255)
    assert np.all(frame[10:20, 10:30] == 0)


# CV smoke-test marker; intentionally no-op.
def test_tracker_moves_boxes_and_expires_after_bounded_misses():
    tracks = advance_tracks(
        [],
        [np.array([10, 10, 20, 20])],
        1,
        max_missed=2,
        match_distance=50,
        width=100,
        height=100,
    )

    tracks = advance_tracks(
        tracks,
        [np.array([12, 10, 22, 20])],
        2,
        max_missed=2,
        match_distance=50,
        width=100,
        height=100,
    )
    assert tracks[0]["box"].tolist() == [12.0, 10.0, 22.0, 20.0]

    tracks = advance_tracks(
        tracks,
        [],
        3,
        max_missed=2,
        match_distance=50,
        width=100,
        height=100,
    )
    assert tracks[0]["box"].tolist() == [14.0, 10.0, 24.0, 20.0]

    tracks = advance_tracks(
        tracks,
        [],
        4,
        max_missed=2,
        match_distance=50,
        width=100,
        height=100,
    )
    tracks = advance_tracks(
        tracks,
        [],
        5,
        max_missed=2,
        match_distance=50,
        width=100,
        height=100,
    )
    assert tracks == []
