import argparse
import sys
import re
from pathlib import Path

import cv2
from ultralytics import YOLO
import torch

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
    """Expand a box by pad_ratio on each side, to compensate for motion that
    happens between two detection frames when frame-skipping is enabled."""
    w, h = x2 - x1, y2 - y1
    px, py = w * pad_ratio, h * pad_ratio
    return clip_box(x1 - px, y1 - py, x2 + px, y2 + py, width, height)


def blur_region(frame, x1, y1, x2, y2, dynamic_kernel=True, fixed_kernel=51):
    """dynamic_kernel scales blur strength to box size (used for plates, whose
    size varies a lot); fixed_kernel is a flat odd kernel (used for faces)."""
    if x2 <= x1 or y2 <= y1:
        return
    roi = frame[y1:y2, x1:x2]
    if dynamic_kernel:
        kx, ky = (x2 - x1) // 3, (y2 - y1) // 3
        kx = max(3, kx + 1 if kx % 2 == 0 else kx)
        ky = max(3, ky + 1 if ky % 2 == 0 else ky)
        frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kx, ky), 0)
    else:
        k = fixed_kernel if fixed_kernel % 2 == 1 else fixed_kernel + 1
        frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


def update_buffer(buffer, current_boxes, frame_idx, dedup_dist=50):
    """Merge freshly-detected boxes into a persistence buffer, replacing any
    old entry that's close to a new detection (same physical object)."""
    for box in current_boxes:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        kept = []
        for d in buffer:
            ob = d['box']
            ocx, ocy = (ob[0] + ob[2]) / 2, (ob[1] + ob[3]) / 2
            if ((cx - ocx) ** 2 + (cy - ocy) ** 2) ** 0.5 > dedup_dist:
                kept.append(d)
        buffer = kept
        buffer.append({'box': box, 'last_seen': frame_idx})
    return buffer


def expire_buffer(buffer, frame_idx, persist_frames):
    return [d for d in buffer if (frame_idx - d['last_seen']) <= persist_frames]


def main():
    parser = argparse.ArgumentParser(
        description="Run YOLOv8 license-plate detection and YOLOv8-face detection on the same "
                     "video, blurring both in a single pass. Speed-optimized: auto GPU/FP16, "
                     "frame-skip detection with position-holding."
    )
    parser.add_argument("--source", type=str, required=True,
                         help="Path to video file or integer for webcam index")

    # Resolve model paths relative to this file:
    # src/services/detect_and_blur.py -> src/models/*.pt
    src_dir = Path(__file__).resolve().parent.parent
    default_plate_weights = src_dir / "models" / "best_cv.pt"
    default_face_weights = src_dir / "models" / "face_yolov8n.pt"

    parser.add_argument("--plate-weights", type=str, default=str(default_plate_weights))
    parser.add_argument("--face-weights", type=str, default=str(default_face_weights))
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--face-conf", type=float, default=0.30)
    parser.add_argument("--imgsz", type=int, default=640,
                         help="Inference resolution for both models. Lower = faster, "
                              "slightly less accurate on small/far objects (default: 640, "
                              "try 480 for a good speed/accuracy balance)")
    parser.add_argument("--detect-every", type=int, default=2,
                         help="Run detection every N frames; frames in between reuse the last "
                              "known box positions. 1 = detect every frame (slowest, most accurate). "
                              "2-3 = good speed/accuracy balance (default: 2)")
    parser.add_argument("--pad-ratio", type=float, default=0.12,
                         help="Expand each blurred box by this fraction on every side, to "
                              "compensate for motion between detection frames (default: 0.12)")
    parser.add_argument("--persist-seconds", type=float, default=0.15,
                         help="How long a box stays blurred after last detected, to bridge "
                              "skipped frames and avoid flicker (default: 0.15s)")

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

    # Persistence must cover at least the frame-skip gap, or boxes would
    # disappear right before the next detection cycle refreshes them.
    persist_frames = max(int(round(args.persist_seconds * fps)), args.detect_every)

    print(f"Video: {width}x{height} @ {fps:.2f}fps, {total_frames} frames")
    print(f"Config: imgsz={args.imgsz}, detect_every={args.detect_every}, "
          f"pad_ratio={args.pad_ratio}, persist_frames={persist_frames}")

    run_dir = get_next_run_dir(base_dir="D:\\Tailieu-2026\\vin\\Demo_day\\Vid\\output")
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / "run.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_video = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    plate_buffer, face_buffer = [], []
    frame_idx = 0
    print(f"Starting inference on source: {source}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # Only run the (expensive) model forward pass every N frames.
        if (frame_idx - 1) % args.detect_every == 0:
            plate_res = plate_model.predict(source=frame, conf=args.plate_conf, imgsz=args.imgsz,
                                             device=device, quantize=quantize, verbose=False)[0]
            face_res = face_model.predict(source=frame, conf=args.face_conf, imgsz=args.imgsz,
                                           device=device, quantize=quantize, verbose=False)[0]

            plate_boxes = [b.xyxy[0].cpu().numpy() for b in plate_res.boxes] if len(plate_res.boxes) else []
            face_boxes = [b for b in face_res.boxes.xyxy.cpu().numpy()] if len(face_res.boxes) else []

            plate_buffer = update_buffer(plate_buffer, plate_boxes, frame_idx, dedup_dist=50)
            face_buffer = update_buffer(face_buffer, face_boxes, frame_idx, dedup_dist=40)

        plate_buffer = expire_buffer(plate_buffer, frame_idx, persist_frames)
        face_buffer = expire_buffer(face_buffer, frame_idx, persist_frames)

        for d in plate_buffer:
            x1, y1, x2, y2 = pad_box(*d['box'], args.pad_ratio, width, height)
            blur_region(frame, x1, y1, x2, y2, dynamic_kernel=True)

        for d in face_buffer:
            x1, y1, x2, y2 = pad_box(*d['box'], args.pad_ratio, width, height)
            blur_region(frame, x1, y1, x2, y2, dynamic_kernel=False, fixed_kernel=51)

        out_video.write(frame)
        if total_frames:
            print(f"  Processed {frame_idx}/{total_frames} frames", end="\r")

    cap.release()
    out_video.release()

    print("\nInference complete!")
    print(f"Output (plates + faces blurred) saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
