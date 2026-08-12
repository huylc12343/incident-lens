# CV validation report

Run date: 2026-08-12. All measurements used CUDA FP16 on `NVIDIA GeForce RTX 3050 Ti Laptop GPU` (`torch 2.12.1+cu132`) and the same every-10th-frame benchmark for both bundled videos.

## Ground truth and reproducibility

The benchmark is implemented in [`scripts/evaluate_cv_recall.py`](../scripts/evaluate_cv_recall.py) and uses [`eval/cv_benchmark/annotations.json`](../eval/cv_benchmark/annotations.json). It reads each video prefix up to the last labelled frame and scores the labelled frames at IoU >= 0.30. The checked-in labels are a minimal manually reviewed subset: 12 plate boxes (7 bridge, 5 intersection) and zero resolvable face boxes. Consequently, face recall is `N/A`, not zero. This is a regression yardstick, not enough evidence for a deployment claim; add at least 100-200 independently labelled frames, including a face-bearing source video, before production sign-off.

Example final run:

```powershell
$env:PYTHONPATH=(Get-Location).Path
& .venv\Scripts\python.exe scripts\evaluate_cv_recall.py `
  --annotations eval\cv_benchmark\annotations.json `
  --imgsz 1280 --plate-conf 0.05 --face-conf 0.05 `
  --detect-every 1 --persist-frames 5
```

`--detect-every 2` is retained in the evaluator only to reproduce the old baseline. The production detector no longer exposes or uses that skip setting.

## Per-frame pipeline

In [`src/services/detect_and_blur.py`](../src/services/detect_and_blur.py):

1. `VideoCapture.read()` obtains a BGR frame (main loop around line 307).
2. Plate and face YOLO models run sequentially on that same frame on every frame (lines 316-321). `conf`, `imgsz`, optional TTA, device, and FP16 are configurable.
3. Detection tensors are transferred once to CPU NumPy arrays (lines 323-324).
4. `advance_tracks()` associates detections and predicts short misses with measured constant velocity (lines 326-335); it does not freeze a stale box.
5. Each active track is padded and blurred in-place on its ROI. Plate and face kernels scale with the smaller box side and are bounded independently (lines 339-353; helper lines 52-92).
6. A missed detection continues using the predicted track only within the bounded window. Once it expires, the track is dropped and the frame is written normally; no full-frame blackout is applied.
7. The resulting frame is written once (line 431).

## Measured before/after results

`inference_fps` below means model-pair frames per measured inference second, not video decode FPS. `recall` is plate matched/ground-truth boxes; face is `N/A` because the denominator is zero.

| Stage/configuration | Bridge recall | Intersection recall | Bridge inference | Intersection inference |
| --- | ---: | ---: | ---: | ---: |
| Baseline: 640, plate .25/face .30, skip 2 + legacy hold | 0/7 (0%) | 0/5 (0%) | 11.269 s, 5.41 fps | 21.295 s, 23.53 fps |
| Step 2: 640, same conf, per-frame + velocity tracker | 0/7 (0%) | 0/5 (0%) | 7.784 s, 15.67 fps | 33.176 s, 30.20 fps |
| Step 3: 960, plate/face .05 | 0/7 (0%) | 0/5 (0%) | 9.956 s, 12.25 fps | 46.718 s, 21.45 fps |
| Step 3: 1280, plate/face .05 (final) | 0/7 (0%) | 0/5 (0%) | 13.566 s, 8.99 fps | 70.042 s, 14.31 fps |
| 1280, plate/face .01 | 0/7 (0%) | 0/5 (0%) | 12.124 s, 10.06 fps | 71.657 s, 13.98 fps |
| 1280, .01 + TTA | 0/7 (0%) | 0/5 (0%) | 24.530 s, 4.97 fps | 169.762 s, 5.90 fps |

### Step 2 decision

The old path invoked the model on 61/501 frames. Per-frame detection invoked it on 122/1002 frames. At 640, measured throughput was 15.67 fps on the 15-fps bridge and 30.20 fps on the 30-fps intersection, while eliminating frozen boxes. Full per-frame detection was therefore selected over the old skip path. The sparse benchmark did not improve recall because the model produced no matching plate boxes; this is a detector/model-data problem, not evidence that stale reuse was safe.

### Step 3 decision

`conf` and `imgsz` are now CLI-configurable, with defaults `.05/.05` and `1280`. The 1280 setting is slower than 960 and still did not match a labelled plate. Lowering to `.01` generated more low-confidence predictions but no matched ground-truth box. TTA added roughly 2.0x bridge and 2.4x intersection time versus the non-TTA 1280/.01 runs in this measurement and also produced zero recall gain, so it remains opt-in (`--augment`). Tiled inference was not enabled: the measured model/footage mismatch was already decisive, and a tile implementation without project labels would create an unverified speed/false-positive surface.

### Step 4 policy

The benchmark was rerun after the adaptive-kernel and bounded-track changes with the final 1280/.05 configuration: plate recall stayed 0/7 on bridge and 0/5 on intersection (0% -> 0%); face remained `N/A`. These changes strengthen blur coverage during short misses without blacking out large portions of the video, but cannot recover an object the detector never localized.

- Plate kernel: `round(0.75 * min(width, height))`, clamped to odd `[15, 151]`.
- Face kernel: `round(0.60 * min(width, height))`, clamped to odd `[31, 301]`.
- A confirmed track may be predicted for `round(persist_seconds * fps)` misses (default 0.15 s), using measured velocity and a 20% box pad.
- On expiry, the track is removed and no stale region is blurred. The frame remains usable; no full-frame blackout is performed.
- If an object was never detected, no tracker can know its position; the benchmark/model validation gap must be closed before claiming near-total redaction.

## Model validation verdict

`best_cv.pt` reports strong source-dataset checkpoint metrics (precision 0.9875, recall 0.99408, mAP50 0.99428, mAP50-95 0.89679), but its checkpoint identifies an unrelated Kaggle training dataset. On the project subset it matched 0/12 labelled plates at every tested configuration. `face_yolov8n.pt` has no recorded validation metrics in its checkpoint, and the supplied videos contain no clearly resolvable face labels. Neither model is production-ready for this footage. Collect and label project-camera plates and faces across distance, angle, blur, lighting, occlusion, and motion, then fine-tune/revalidate before deployment.

## Verification and scope

The full test suite passes, including CV tests for adaptive kernel adequacy, in-place ROI behaviour, and bounded tracker expiration. No API or Docker changes were made because the backend currently exposes only chat/status and video-through-backend use was not confirmed.
