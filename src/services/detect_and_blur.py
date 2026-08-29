import argparse
import re
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from src.models.incidents import NativeVideoMetadata
from src.services.media import NormalizedVideoArtifact

# --- Fix for PyTorch >=2.6 "weights_only" default change ---
# torch.load() now defaults to weights_only=True, which blocks unpickling the
# many classes packed inside a YOLO checkpoint. Both weight files below are
# from trusted sources (our own training run + a known public repo), so we
# force weights_only=False globally instead of allow-listing each class.
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

#


def get_next_run_dir(base_dir="runs/detect"):
    """Scans base_dir for folders named run_<number> and returns the next one."""
    base_path = Path(base_dir)
    if not base_path.exists():
        return base_path / "run_1"

    max_num = 0
    for item in base_path.iterdir():
        if item.is_dir():
            match = re.match(r"^run_(\d+)$", item.name)
            if match:
                max_num = max(max_num, int(match.group(1)))

    return base_path / f"run_{max_num + 1}"


def clip_box(x1, y1, x2, y2, width, height):
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(width - 1, int(x2)), min(height - 1, int(y2))
    return x1, y1, x2, y2


def pad_box(x1, y1, x2, y2, pad_ratio, width, height):
    """Expand a box by ``pad_ratio`` on each side and clip it to the frame."""
    w, h = x2 - x1, y2 - y1
    px, py = w * pad_ratio, h * pad_ratio
    return clip_box(x1 - px, y1 - py, x2 + px, y2 + py, width, height)


def blur_region(
    frame,
    x1,
    y1,
    x2,
    y2,
    *,
    kernel_ratio,
    min_kernel,
    max_kernel,
):
    """Blur one ROI in-place with a bounded size-scaled kernel."""
    if x2 <= x1 or y2 <= y1:
        return
    roi = frame[y1:y2, x1:x2]
    kernel = adaptive_kernel_size(x2 - x1, y2 - y1, kernel_ratio, min_kernel, max_kernel)
    frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kernel, kernel), 0)


def adaptive_kernel_size(width, height, ratio, min_kernel, max_kernel):
    """Return an odd Gaussian kernel proportional to the redaction ROI.

    The minimum prevents tiny license plates from receiving an effectively
    transparent blur, while the maximum bounds CPU work for close-up faces.
    ``cv2.GaussianBlur`` accepts kernels larger than the ROI, which is useful
    for very small plates and keeps the redaction strong.
    """
    span = max(1, min(int(width), int(height)))
    minimum = max(1, int(min_kernel))
    if minimum % 2 == 0:
        minimum += 1
    maximum = max(minimum, int(max_kernel))
    if maximum % 2 == 0:
        maximum = maximum - 1 if maximum > minimum else minimum
    kernel = int(round(span * float(ratio)))
    kernel = max(minimum, min(maximum, kernel))
    if kernel % 2 == 0:
        kernel += 1
    if kernel > maximum:
        kernel = maximum
    return kernel


def redaction_detection_interval(source_fps: float, target_detection_fps: float) -> int:
    """Return the frame stride that best caps detector inference frequency."""
    if source_fps <= 0 or target_detection_fps <= 0:
        raise ValueError("source and target detection FPS must be positive")
    return max(1, int(round(source_fps / target_detection_fps)))


def _box_iou(left, right):
    """Small NumPy-free IoU helper used by the lightweight local tracker."""
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def advance_tracks(
    tracks,
    current_boxes,
    frame_idx,
    *,
    max_missed,
    match_distance,
    width,
    height,
):
    """Update a bounded constant-velocity track set.

    Detection is still performed on every frame. When a model misses briefly,
    the last confirmed box is moved by its measured velocity; it is never
    held frozen. A track is removed after ``max_missed`` consecutive misses
    and is removed after the bounded miss window expires.
    """
    detections = [np.asarray(box, dtype=np.float32).copy() for box in current_boxes]
    candidates = []
    for track in tracks:
        previous = np.asarray(track["box"], dtype=np.float32)
        gap = max(1, int(frame_idx - track["last_update"]))
        predicted = previous + np.asarray(track["velocity"], dtype=np.float32) * gap
        x1, y1, x2, y2 = clip_box(*predicted, width, height)
        candidates.append((track, np.asarray([x1, y1, x2, y2], dtype=np.float32)))

    unmatched_detections = set(range(len(detections)))
    updated = []
    for track, predicted in candidates:
        best_index = None
        best_score = 0.0
        for index in unmatched_detections:
            detection = detections[index]
            iou = _box_iou(predicted, detection)
            pcx = (predicted[0] + predicted[2]) / 2
            pcy = (predicted[1] + predicted[3]) / 2
            dcx = (detection[0] + detection[2]) / 2
            dcy = (detection[1] + detection[3]) / 2
            distance = float(np.hypot(dcx - pcx, dcy - pcy))
            score = iou if iou >= 0.05 else max(0.0, 1.0 - distance / max(1.0, match_distance))
            if (iou >= 0.05 or distance <= match_distance) and score > best_score:
                best_index, best_score = index, score

        if best_index is not None:
            detection = detections.pop(best_index)
            unmatched_detections = {i - (i > best_index) for i in unmatched_detections if i != best_index}
            old_box = np.asarray(track["box"], dtype=np.float32)
            gap = max(1, int(frame_idx - track["last_update"]))
            track["velocity"] = (detection - old_box) / gap
            x1, y1, x2, y2 = clip_box(*detection, width, height)
            track.update({
                "box": np.asarray([x1, y1, x2, y2], dtype=np.float32),
                "last_update": frame_idx,
                "missed": 0,
            })
            updated.append(track)
        else:
            track["box"] = predicted
            track["last_update"] = frame_idx
            track["missed"] += 1
            if track["missed"] <= max_missed:
                updated.append(track)

    # Any detections not assigned to an existing track start a new confirmed track.
    for detection in detections:
        x1, y1, x2, y2 = clip_box(*detection, width, height)
        updated.append({
            "box": np.asarray([x1, y1, x2, y2], dtype=np.float32),
            "velocity": np.zeros(4, dtype=np.float32),
            "last_update": frame_idx,
            "missed": 0,
        })

    return updated


@lru_cache(maxsize=2)
def _load_yolo(weights_path: str) -> YOLO:
    """Load each local weight file once for the lifetime of this process."""
    return YOLO(weights_path)


def redact_video(
    source_uri: str,
    output_uri: str,
    *,
    plate_weights: str | Path | None = None,
    face_weights: str | Path | None = None,
    plate_conf: float = 0.05,
    face_conf: float = 0.05,
    imgsz: int = 512,
    detection_fps: float | None = None,
    augment: bool = False,
    pad_ratio: float = 0.20,
    persist_seconds: float = 0.15,
    track_match_distance: float = 80.0,
    plate_kernel_ratio: float = 0.75,
    plate_min_kernel: int = 15,
    plate_max_kernel: int = 151,
    face_kernel_ratio: float = 0.60,
    face_min_kernel: int = 31,
    face_max_kernel: int = 301,
) -> NormalizedVideoArtifact:
    """Blur detected license plates and faces from ``source_uri`` into ``output_uri``.

    This is a synchronous, CPU/GPU-bound operation. Call it through
    ``asyncio.to_thread`` from an async workflow. The returned artifact can be
    assigned directly to a native VLM request's ``normalized_video_uri``.

    ``detection_fps`` caps how often the two detectors run, in detections per
    second of source footage; the tracker bridges the frames in between and
    every frame is still blurred and written. ``None`` detects on every frame.
    Capping it is the main speed lever here, and it is a privacy trade: an
    object appearing and leaving inside one gap is never localized, so it is
    never blurred.
    """
    source = Path(source_uri).resolve()
    output = Path(output_uri).resolve()
    src_dir = Path(__file__).resolve().parent.parent
    plate_weights_path = Path(plate_weights or src_dir / "models" / "best_plate.pt").resolve()
    face_weights_path = Path(face_weights or src_dir / "models" / "best3_face.pt").resolve()

    if not source.is_file():
        raise FileNotFoundError(f"video source file not found: {source}")
    if source == output:
        raise ValueError("output_uri must differ from source_uri")
    if not plate_weights_path.is_file():
        raise FileNotFoundError(f"plate weights file not found: {plate_weights_path}")
    if not face_weights_path.is_file():
        raise FileNotFoundError(f"face weights file not found: {face_weights_path}")
    if min(plate_conf, face_conf) < 0 or max(plate_conf, face_conf) > 1:
        raise ValueError("detection confidence thresholds must be between 0 and 1")
    if imgsz <= 0 or min(pad_ratio, persist_seconds, track_match_distance) < 0:
        raise ValueError("redaction dimensions and tracking parameters must be valid")
    if detection_fps is not None and detection_fps <= 0:
        raise ValueError("detection_fps must be positive when set")

    use_cuda = torch.cuda.is_available()
    device = 0 if use_cuda else "cpu"
    plate_model = _load_yolo(str(plate_weights_path))
    face_model = _load_yolo(str(face_weights_path))

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video source: {source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("video source has invalid dimensions")

    output.parent.mkdir(parents=True, exist_ok=True)
    out_video = cv2.VideoWriter(
        str(output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not out_video.isOpened():
        cap.release()
        raise RuntimeError(f"could not open video output: {output}")

    persist_frames = max(1, int(round(persist_seconds * fps)))
    # Detection is the dominant cost, so cap how often it runs rather than
    # tying it to the source frame rate. ``detection_fps=None`` keeps the
    # every-frame behaviour.
    detect_every = redaction_detection_interval(fps, detection_fps) if detection_fps else 1
    # A confirmed track has to survive the whole gap between detections. Without
    # this, a stride wider than the persistence window expires every box in
    # between and the redaction flickers off.
    max_missed = max(persist_frames, detect_every)
    plate_tracks, face_tracks = [], []
    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1

            if (frame_idx - 1) % detect_every == 0:
                plate_res = plate_model.predict(
                    source=frame,
                    conf=plate_conf,
                    imgsz=imgsz,
                    device=device,
                    quantize=16 if use_cuda else None,
                    augment=augment,
                    verbose=False,
                )[0]
                face_res = face_model.predict(
                    source=frame,
                    conf=face_conf,
                    imgsz=imgsz,
                    device=device,
                    quantize=16 if use_cuda else None,
                    augment=augment,
                    verbose=False,
                )[0]
                plate_boxes = [box.xyxy[0].cpu().numpy() for box in plate_res.boxes] if len(plate_res.boxes) else []
                face_boxes = [box for box in face_res.boxes.xyxy.cpu().numpy()] if len(face_res.boxes) else []
            else:
                # No model runs on this frame; every confirmed track coasts along
                # its measured velocity until the next detection corrects it.
                plate_boxes, face_boxes = [], []

            plate_tracks = advance_tracks(
                plate_tracks,
                plate_boxes,
                frame_idx,
                max_missed=max_missed,
                match_distance=track_match_distance,
                width=width,
                height=height,
            )
            face_tracks = advance_tracks(
                face_tracks,
                face_boxes,
                frame_idx,
                max_missed=max_missed,
                match_distance=track_match_distance,
                width=width,
                height=height,
            )
            for track in plate_tracks:
                x1, y1, x2, y2 = pad_box(*track["box"], pad_ratio, width, height)
                blur_region(
                    frame,
                    x1,
                    y1,
                    x2,
                    y2,
                    kernel_ratio=plate_kernel_ratio,
                    min_kernel=plate_min_kernel,
                    max_kernel=plate_max_kernel,
                )
            for track in face_tracks:
                x1, y1, x2, y2 = pad_box(*track["box"], pad_ratio, width, height)
                blur_region(
                    frame,
                    x1,
                    y1,
                    x2,
                    y2,
                    kernel_ratio=face_kernel_ratio,
                    min_kernel=face_min_kernel,
                    max_kernel=face_max_kernel,
                )
            out_video.write(frame)
    finally:
        cap.release()
        out_video.release()

    if frame_idx == 0:
        raise RuntimeError("video source contains no readable frames")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("redaction did not create an output video")
    return NormalizedVideoArtifact(
        uri=str(output),
        metadata=NativeVideoMetadata(
            duration_s=frame_idx / fps,
            width=width,
            height=height,
            fps=fps,
            size_bytes=output.stat().st_size,
        ),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run YOLOv8 license-plate detection and YOLOv8-face detection on the same "
                     "video, blurring both in a single pass. Detection runs on every frame; "
                     "a bounded constant-velocity track bridges short detector misses."
    )
    parser.add_argument("--source", type=str, required=True,
                         help="Path to video file or integer for webcam index")
    parser.add_argument("--output", type=str, default=None,
                        help="Path for the redacted MP4 output (default: next runs/detect/run_N/run.mp4)")

    # Resolve model paths relative to this file:
    # src/services/detect_and_blur.py -> src/models/*.pt
    src_dir = Path(__file__).resolve().parent.parent
    default_plate_weights = src_dir / "models" / "best_plate.pt"
    default_face_weights = src_dir / "models" / "best3_face.pt"

    parser.add_argument("--plate-weights", type=str, default=str(default_plate_weights))
    parser.add_argument("--face-weights", type=str, default=str(default_face_weights))
    parser.add_argument("--plate-conf", type=float, default=0.05,
                         help="Plate confidence threshold (default: 0.05; lower improves "
                              "recall but increases false positives).")
    parser.add_argument("--face-conf", type=float, default=0.05,
                         help="Face confidence threshold (default: 0.05; lower improves "
                              "recall but increases false positives).")
    parser.add_argument("--imgsz", type=int, default=512,
                         help="Inference resolution for both models. Lower = faster, "
                         "slightly less accurate on small/far objects (default: 512)")
    parser.add_argument("--detection-fps", type=float, default=None,
                         help="Cap detector runs to this many per second of footage; the "
                              "tracker bridges the gap and every frame is still blurred. "
                              "Unset detects on every frame. Lower is faster but can miss "
                              "an object that appears and leaves inside one gap.")
    parser.add_argument("--augment", action="store_true",
                         help="Enable Ultralytics test-time augmentation (measured slower; "
                              "off by default).")
    parser.add_argument("--pad-ratio", type=float, default=0.20,
                         help="Expand each blurred box by this fraction on every side, to "
                              "cover detector/track uncertainty (default: 0.20)")
    parser.add_argument("--persist-seconds", type=float, default=0.15,
                         help="Maximum time a missed track is predicted before it expires "
                              "(default: 0.15s)")
    parser.add_argument("--track-match-distance", type=float, default=80.0,
                         help="Maximum center displacement for associating a detection with "
                              "an existing track (pixels, default: 80)")
    parser.add_argument("--plate-kernel-ratio", type=float, default=0.75,
                         help="Plate Gaussian kernel as a fraction of the smaller box side "
                              "(default: 0.75)")
    parser.add_argument("--plate-min-kernel", type=int, default=15,
                         help="Minimum odd plate blur kernel (default: 15)")
    parser.add_argument("--plate-max-kernel", type=int, default=151,
                         help="Maximum plate blur kernel (default: 151)")
    parser.add_argument("--face-kernel-ratio", type=float, default=0.60,
                         help="Face Gaussian kernel as a fraction of the smaller box side "
                              "(default: 0.60)")
    parser.add_argument("--face-min-kernel", type=int, default=31,
                         help="Minimum odd face blur kernel (default: 31)")
    parser.add_argument("--face-max-kernel", type=int, default=301,
                         help="Maximum face blur kernel (default: 301)")
    args = parser.parse_args()

    # The service accepts local files only; webcam input remains a CLI-only
    # concern and is intentionally rejected rather than producing an artifact
    # with an undefined destination duration.
    source_str = args.source.strip()
    if source_str.isdigit():
        parser.error("webcam input is not supported when producing a video artifact")
    run_dir = get_next_run_dir() if args.output is None else None
    output_path = Path(args.output) if args.output else run_dir / "run.mp4"
    artifact = redact_video(
        source_str,
        str(output_path),
        plate_weights=args.plate_weights,
        face_weights=args.face_weights,
        plate_conf=args.plate_conf,
        face_conf=args.face_conf,
        imgsz=args.imgsz,
        detection_fps=args.detection_fps,
        augment=args.augment,
        pad_ratio=args.pad_ratio,
        persist_seconds=args.persist_seconds,
        track_match_distance=args.track_match_distance,
        plate_kernel_ratio=args.plate_kernel_ratio,
        plate_min_kernel=args.plate_min_kernel,
        plate_max_kernel=args.plate_max_kernel,
        face_kernel_ratio=args.face_kernel_ratio,
        face_min_kernel=args.face_min_kernel,
        face_max_kernel=args.face_max_kernel,
    )
    print(f"Output (plates + faces blurred) saved to: {artifact.uri}")


if __name__ == "__main__":
    main()
