import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

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


def main():
    parser = argparse.ArgumentParser(
        description="Run YOLOv8 license-plate detection and YOLOv8-face detection on the same "
                     "video, blurring both in a single pass. Detection runs on every frame; "
                     "a bounded constant-velocity track bridges short detector misses."
    )
    parser.add_argument("--source", type=str, required=True,
                         help="Path to video file or integer for webcam index")

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
    parser.add_argument("--imgsz", type=int, default=1280,
                         help="Inference resolution for both models. Lower = faster, "
                         "slightly less accurate on small/far objects (default: 1280, "
                         "try 960 for a speed/accuracy tradeoff)")
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

    # --- Resolve and validate source ---
    source_str = args.source.strip()
    if source_str.isdigit():
        source = int(source_str)
    else:
        source = source_str
        if not Path(source).exists():
            print(f"Error: Video source file not found at: '{source}'")
            print("Gợi ý: dùng ngoặc kép \"\" để bọc đường dẫn có khoảng trắng.")
            sys.exit(1)

    plate_weights_str = args.plate_weights.strip()
    face_weights_str = args.face_weights.strip()
    if not Path(plate_weights_str).exists():
        print(f"Error: Plate weights file not found at: '{plate_weights_str}'")
        sys.exit(1)
    if not Path(face_weights_str).exists():
        print(f"Error: Face weights file not found at: '{face_weights_str}'")
        sys.exit(1)

    # --- Auto device + inference precision detection ---
    use_cuda = torch.cuda.is_available()
    device = 0 if use_cuda else "cpu"
    quantize = 16 if use_cuda else None  # FP16 on CUDA, FP32 on CPU
    print(f"Device: {'GPU (cuda:0)' if use_cuda else 'CPU'}"
          f"{' + FP16' if quantize == 16 else ''}")
    if not use_cuda:
        print("⚠ Không phát hiện GPU khả dụng (torch.cuda.is_available() = False).")
        print("  Nếu máy có GPU NVIDIA, kiểm tra lại driver/CUDA và bản torch đã cài "
              "(torch+cu1xx) - đây thường là điểm tối ưu tốc độ lớn nhất.")

    print(f"Loading plate model from: {plate_weights_str}")
    plate_model = YOLO(plate_weights_str)
    print(f"Loading face model from: {face_weights_str}")
    face_model = YOLO(face_weights_str)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # With per-frame detection this is solely the bounded prediction window;
    # there is no frame-skip gap to hide with a stale box.
    persist_frames = max(1, int(round(args.persist_seconds * fps)))

    print(f"Video: {width}x{height} @ {fps:.2f}fps, {total_frames} frames")
    print(f"Config: imgsz={args.imgsz}, per_frame_detection=True, "
          f"pad_ratio={args.pad_ratio}, persist_frames={persist_frames}, "
          f"match_distance={args.track_match_distance}, "
          f"plate_kernel={args.plate_min_kernel}-{args.plate_max_kernel}@{args.plate_kernel_ratio}, "
          f"face_kernel={args.face_min_kernel}-{args.face_max_kernel}@{args.face_kernel_ratio}")

    run_dir = get_next_run_dir(base_dir="D:\\Tailieu-2026\\vin\\Demo_day\\Vid\\output")
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / "run.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_video = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    plate_tracks, face_tracks = [], []
    frame_idx = 0
    print(f"Starting inference on source: {source}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # Full per-frame inference removes the confirmed stale-box failure
        # mode. The track only bridges a short miss with measured motion.
        plate_res = plate_model.predict(source=frame, conf=args.plate_conf, imgsz=args.imgsz,
                                         device=device, quantize=quantize,
                                         augment=args.augment, verbose=False)[0]
        face_res = face_model.predict(source=frame, conf=args.face_conf, imgsz=args.imgsz,
                                       device=device, quantize=quantize,
                                       augment=args.augment, verbose=False)[0]

        plate_boxes = [b.xyxy[0].cpu().numpy() for b in plate_res.boxes] if len(plate_res.boxes) else []
        face_boxes = [b for b in face_res.boxes.xyxy.cpu().numpy()] if len(face_res.boxes) else []

        plate_tracks = advance_tracks(
            plate_tracks, plate_boxes, frame_idx,
            max_missed=persist_frames, match_distance=args.track_match_distance,
            width=width, height=height,
        )
        face_tracks = advance_tracks(
            face_tracks, face_boxes, frame_idx,
            max_missed=persist_frames, match_distance=args.track_match_distance,
            width=width, height=height,
        )

        for track in plate_tracks:
            x1, y1, x2, y2 = pad_box(*track['box'], args.pad_ratio, width, height)
            blur_region(
                frame, x1, y1, x2, y2,
                kernel_ratio=args.plate_kernel_ratio,
                min_kernel=args.plate_min_kernel,
                max_kernel=args.plate_max_kernel,
            )

        for track in face_tracks:
            x1, y1, x2, y2 = pad_box(*track['box'], args.pad_ratio, width, height)
            blur_region(
                frame, x1, y1, x2, y2,
                kernel_ratio=args.face_kernel_ratio,
                min_kernel=args.face_min_kernel,
                max_kernel=args.face_max_kernel,
            )

        out_video.write(frame)
        if total_frames:
            print(f"  Processed {frame_idx}/{total_frames} frames", end="\r")

    cap.release()
    out_video.release()

    print("\nInference complete!")
    print(f"Output (plates + faces blurred) saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
