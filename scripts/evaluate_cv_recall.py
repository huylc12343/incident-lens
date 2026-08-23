"""Measure frame-level plate/face recall on the checked-in CV benchmark.

The evaluator intentionally runs the complete video prefix up to each labelled
frame. That preserves the temporal behaviour of the pipeline, including the
old skip-and-hold path, while scoring only the every-10th labelled frames.
It does not create or modify project outputs.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from src.services.detect_and_blur import advance_tracks


def _legacy_update_buffer(buffer, current_boxes, frame_idx, dedup_dist=50):
    """Reproduce the pre-tracker baseline without keeping legacy code in CV runtime."""
    for box in current_boxes:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        kept = []
        for entry in buffer:
            old_box = entry["box"]
            old_cx, old_cy = (old_box[0] + old_box[2]) / 2, (old_box[1] + old_box[3]) / 2
            if ((cx - old_cx) ** 2 + (cy - old_cy) ** 2) ** 0.5 > dedup_dist:
                kept.append(entry)
        buffer = kept
        buffer.append({"box": box, "last_seen": frame_idx})
    return buffer


def _legacy_expire_buffer(buffer, frame_idx, persist_frames):
    return [entry for entry in buffer if (frame_idx - entry["last_seen"]) <= persist_frames]


def iou_xyxy(left: list[float], right: list[float]) -> float:
    ax1, ay1, ax2, ay2 = left
    bx1, by1, bx2, by2 = right
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def _boxes(result: Any) -> list[np.ndarray]:
    if not len(result.boxes):
        return []
    return [box for box in result.boxes.xyxy.detach().cpu().numpy()]


def _score_frame(
    predicted: dict[str, list[np.ndarray]],
    expected: dict[str, list[list[float]]],
    iou_threshold: float,
) -> dict[str, dict[str, int]]:
    score: dict[str, dict[str, int]] = {}
    for class_name in ("plate", "face"):
        truths = expected.get(class_name, [])
        predictions = predicted.get(class_name, [])
        matched = sum(
            any(iou_xyxy(truth, prediction.tolist()) >= iou_threshold for prediction in predictions)
            for truth in truths
        )
        score[class_name] = {
            "ground_truth": len(truths),
            "matched": matched,
            "predictions": len(predictions),
        }
    return score


def evaluate_video(
    video: dict[str, Any],
    plate_model: YOLO,
    face_model: YOLO,
    *,
    plate_conf: float,
    face_conf: float,
    imgsz: int,
    detect_every: int,
    persist_frames: int,
    quantize: int | None,
    iou_threshold: float,
    track_match_distance: float,
    augment: bool,
) -> dict[str, Any]:
    labels = {frame["frame_index"]: frame for frame in video["frames"]}
    last_frame = max(labels)
    cap = cv2.VideoCapture(video["path"])
    if not cap.isOpened():
        raise RuntimeError(f"Could not open benchmark video: {video['path']}")
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    plate_buffer: list[dict[str, Any]] = []
    face_buffer: list[dict[str, Any]] = []
    plate_tracks: list[dict[str, Any]] = []
    face_tracks: list[dict[str, Any]] = []
    scores: dict[str, dict[str, int]] = defaultdict(lambda: {"ground_truth": 0, "matched": 0, "predictions": 0})
    inference_seconds = 0.0
    inference_frames = 0
    frames_read = 0
    use_tracker = detect_every == 1

    while frames_read <= last_frame:
        ok, frame = cap.read()
        if not ok:
            break
        frame_index = frames_read
        frames_read += 1

        if frame_index % detect_every == 0:
            start = time.perf_counter()
            plate_result = plate_model.predict(
                source=frame,
                conf=plate_conf,
                imgsz=imgsz,
                device=0 if torch.cuda.is_available() else "cpu",
                quantize=quantize,
                augment=augment,
                verbose=False,
            )[0]
            face_result = face_model.predict(
                source=frame,
                conf=face_conf,
                imgsz=imgsz,
                device=0 if torch.cuda.is_available() else "cpu",
                quantize=quantize,
                augment=augment,
                verbose=False,
            )[0]
            inference_seconds += time.perf_counter() - start
            inference_frames += 1
            if use_tracker:
                plate_tracks = advance_tracks(
                    plate_tracks, _boxes(plate_result), frame_index,
                    max_missed=persist_frames,
                    match_distance=track_match_distance,
                    width=frame_width,
                    height=frame_height,
                )
                face_tracks = advance_tracks(
                    face_tracks, _boxes(face_result), frame_index,
                    max_missed=persist_frames,
                    match_distance=track_match_distance,
                    width=frame_width,
                    height=frame_height,
                )
            else:
                plate_buffer = _legacy_update_buffer(plate_buffer, _boxes(plate_result), frame_index)
                face_buffer = _legacy_update_buffer(face_buffer, _boxes(face_result), frame_index)

        if not use_tracker:
            plate_buffer = _legacy_expire_buffer(plate_buffer, frame_index, persist_frames)
            face_buffer = _legacy_expire_buffer(face_buffer, frame_index, persist_frames)

        if frame_index not in labels:
            continue
        expected: dict[str, list[list[float]]] = defaultdict(list)
        for obj in labels[frame_index]["objects"]:
            expected[obj["class"]].append(obj["bbox"])
        predicted = {
            "plate": ([entry["box"] for entry in plate_buffer]
                       if not use_tracker else [entry["box"] for entry in plate_tracks]),
            "face": ([entry["box"] for entry in face_buffer]
                      if not use_tracker else [entry["box"] for entry in face_tracks]),
        }
        frame_score = _score_frame(predicted, expected, iou_threshold)
        for class_name, values in frame_score.items():
            for key, value in values.items():
                scores[class_name][key] += value

    cap.release()
    result: dict[str, Any] = {
        "video": video["id"],
        "frames_read": frames_read,
        "labelled_frames": len(labels),
        "inference_seconds": round(inference_seconds, 3),
        "inference_frames": inference_frames,
        "inference_fps": round(inference_frames / inference_seconds, 2) if inference_seconds else None,
        "tracking": use_tracker,
        "scores": {},
    }
    for class_name, values in scores.items():
        denominator = values["ground_truth"]
        result["scores"][class_name] = {
            **values,
            "recall": round(values["matched"] / denominator, 4) if denominator else None,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("eval/cv_benchmark/annotations.json"))
    parser.add_argument("--plate-weights", type=Path, default=Path("src/models/best_cv.pt"))
    parser.add_argument("--face-weights", type=Path, default=Path("src/models/face_yolov8n.pt"))
    parser.add_argument("--plate-conf", type=float, default=0.25)
    parser.add_argument("--face-conf", type=float, default=0.30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--detect-every", type=int, default=2)
    parser.add_argument("--persist-frames", type=int, default=5)
    parser.add_argument("--track-match-distance", type=float, default=80.0)
    parser.add_argument("--augment", action="store_true", help="Enable Ultralytics test-time augmentation.")
    parser.add_argument("--iou-threshold", type=float, default=0.3)
    parser.add_argument("--fp32", action="store_true", help="Use FP32 instead of CUDA FP16.")
    args = parser.parse_args()

    benchmark = json.loads(args.annotations.read_text(encoding="utf-8"))
    plate_model = YOLO(str(args.plate_weights))
    face_model = YOLO(str(args.face_weights))
    quantize = None if args.fp32 else (16 if torch.cuda.is_available() else None)
    results = [
        evaluate_video(
            video,
            plate_model,
            face_model,
            plate_conf=args.plate_conf,
            face_conf=args.face_conf,
            imgsz=args.imgsz,
            detect_every=args.detect_every,
            persist_frames=args.persist_frames,
            quantize=quantize,
            iou_threshold=args.iou_threshold,
            track_match_distance=args.track_match_distance,
            augment=args.augment,
        )
        for video in benchmark["videos"]
    ]
    summary = {
        "device": "cuda:0" if torch.cuda.is_available() else "cpu",
        "torch": torch.__version__,
        "config": {
            "plate_conf": args.plate_conf,
            "face_conf": args.face_conf,
            "imgsz": args.imgsz,
            "detect_every": args.detect_every,
            "persist_frames": args.persist_frames,
            "track_match_distance": args.track_match_distance,
            "augment": args.augment,
            "iou_threshold": args.iou_threshold,
            "quantize": quantize,
        },
        "videos": results,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
