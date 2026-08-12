import cv2
import numpy as np

from src.services.detect_and_blur import (
    adaptive_kernel_size,
    advance_tracks,
    blur_region,
)


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
        kernel_ratio=0.75, min_kernel=15, max_kernel=151,
    )

    assert calls == [((10, 20, 3), (15, 15), 0)]
    assert np.all(frame[:10] == 255)
    assert np.all(frame[20:] == 255)
    assert np.all(frame[:, :10] == 255)
    assert np.all(frame[:, 30:] == 255)
    assert np.all(frame[10:20, 10:30] == 0)


def test_tracker_moves_boxes_and_expires_after_bounded_misses():
    tracks = advance_tracks(
        [], [np.array([10, 10, 20, 20])], 1,
        max_missed=2, match_distance=50, width=100, height=100,
    )

    tracks = advance_tracks(
        tracks, [np.array([12, 10, 22, 20])], 2,
        max_missed=2, match_distance=50, width=100, height=100,
    )
    assert tracks[0]["box"].tolist() == [12.0, 10.0, 22.0, 20.0]

    tracks = advance_tracks(
        tracks, [], 3,
        max_missed=2, match_distance=50, width=100, height=100,
    )
    assert tracks[0]["box"].tolist() == [14.0, 10.0, 24.0, 20.0]

    tracks = advance_tracks(
        tracks, [], 4,
        max_missed=2, match_distance=50, width=100, height=100,
    )
    tracks = advance_tracks(
        tracks, [], 5,
        max_missed=2, match_distance=50, width=100, height=100,
    )
    assert tracks == []
