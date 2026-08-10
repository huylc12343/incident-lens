"""Provider-independent orchestration and validation for VideoMemory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from src.models.incidents import (
    AnalysisMode,
    EvidenceReference,
    NativeVideoAnalysisRequest,
    PromptEnvelope,
    SamplingMetadata,
    TimelineEvent,
    TimestampedFrame,
    TimestampedFramesAnalysisRequest,
    VideoAnalysisRequest,
    VideoMemory,
    VideoMemoryPatch,
    VideoSequenceManifest,
    VLMInputMode,
    VLMService,
)

MemoryItem = TypeVar("MemoryItem", bound=BaseModel)


class VideoMemoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VideoMemoryLimits:
    max_entities: int = 50
    max_timeline_events: int = 6
    max_claims: int = 100

    def __post_init__(self) -> None:
        if min(self.max_entities, self.max_timeline_events, self.max_claims) <= 0:
            raise ValueError("VideoMemory limits must be positive")


@dataclass(frozen=True)
class VideoMemoryWorkflowConfig:
    artifact_dir: str = "./data/artifacts"
    frame_fps: float = 2.0
    frame_width: int = 1024
    frame_height: int = 576
    frame_format: str = "jpeg"
    frame_jpeg_quality: int = 85
    max_frames: int = 120
    max_frames_per_request: int = 120
    frame_overflow_strategy: str = "rolling_batches"
    frame_batch_size: int = 60
    frame_batch_overlap: int = 5
    frame_max_batches: int = 8
    incident_frame_fps: float = 4.0
    incident_max_frames: int = 60
    incident_clip_min_duration_s: float = 5.0
    incident_clip_pre_roll_s: float = 1.0
    incident_clip_post_roll_s: float = 2.0
    video_target_width: int = 1280
    video_target_height: int = 720
    video_target_fps: float = 15.0
    video_codec: str = "libx264"
    video_pixel_format: str = "yuv420p"
    video_max_output_bytes: int = 100_000_000
    max_duration_s: float = 60.0
    prompt_version: str = "v1"
    limits: VideoMemoryLimits = VideoMemoryLimits()

    def __post_init__(self) -> None:
        numeric_values = (
            self.frame_fps,
            self.frame_width,
            self.frame_height,
            self.max_frames,
            self.max_frames_per_request,
            self.frame_batch_size,
            self.frame_max_batches,
            self.incident_frame_fps,
            self.incident_max_frames,
            self.incident_clip_min_duration_s,
            self.video_target_width,
            self.video_target_height,
            self.video_target_fps,
            self.video_max_output_bytes,
            self.max_duration_s,
        )
        if min(numeric_values) <= 0:
            raise ValueError("workflow sizes, rates, and limits must be positive")
        if min(self.incident_clip_pre_roll_s, self.incident_clip_post_roll_s) < 0:
            raise ValueError("incident clip roll durations must be non-negative")
        if self.frame_format not in {"jpeg", "png"}:
            raise ValueError("frame_format must be jpeg or png")
        if not 1 <= self.frame_jpeg_quality <= 100:
            raise ValueError("frame_jpeg_quality must be between 1 and 100")
        if self.frame_overflow_strategy not in {"rolling_batches", "fail"}:
            raise ValueError("frame_overflow_strategy must be rolling_batches or fail")
        if not 0 <= self.frame_batch_overlap < self.frame_batch_size:
            raise ValueError("frame batch overlap must be smaller than batch size")


class VideoMemoryWorkflow:
    def __init__(self, *, vlm: VLMService, config: VideoMemoryWorkflowConfig) -> None:
        self.vlm = vlm
        self.config = config

    async def analyze(self, request: VideoAnalysisRequest) -> VideoMemory:
        if isinstance(request, NativeVideoAnalysisRequest):
            if self.vlm.capabilities.input_mode != VLMInputMode.NATIVE_VIDEO:
                raise VideoMemoryError("VLM_MODE_MISMATCH", "configured VLM does not accept native video")
            return await analyze_single_request(
                vlm=self.vlm,
                request=request,
                source_duration_s=request.metadata.duration_s,
                limits=self.config.limits,
            )

        if self.vlm.capabilities.input_mode != VLMInputMode.TIMESTAMPED_FRAMES:
            raise VideoMemoryError("VLM_MODE_MISMATCH", "configured VLM does not accept timestamped frames")
        provider_limit = self.vlm.capabilities.max_images_per_request
        effective_limit = self.config.max_frames_per_request
        if provider_limit is not None:
            effective_limit = min(effective_limit, provider_limit)
        if len(request.manifest.frames) <= effective_limit:
            return await analyze_single_request(
                vlm=self.vlm,
                request=request,
                source_duration_s=request.manifest.duration_s,
                limits=self.config.limits,
            )
        if self.config.frame_overflow_strategy == "fail":
            raise VideoMemoryError(
                "FRAME_LIMIT_EXCEEDED",
                f"received {len(request.manifest.frames)} frames; request limit is {effective_limit}",
            )
        batch_size = min(self.config.frame_batch_size, effective_limit)
        if self.config.frame_batch_overlap >= batch_size:
            raise VideoMemoryError("ROLLING_BATCH_CONFIG_INVALID", "overlap must be smaller than effective batch size")
        return await analyze_rolling_batches(
            vlm=self.vlm,
            request=request,
            batch_size=batch_size,
            overlap=self.config.frame_batch_overlap,
            max_batches=self.config.frame_max_batches,
            final_frame_limit=effective_limit,
            limits=self.config.limits,
        )


def build_sequence_manifest(
    *,
    frames: list[TimestampedFrame],
    source_video_uri: str,
    duration_s: float,
) -> VideoSequenceManifest:
    """Build a manifest while preserving caller-provided temporal order."""
    return VideoSequenceManifest(
        frames=frames,
        source_video_uri=source_video_uri,
        duration_s=duration_s,
    )


async def analyze_single_request(
    *,
    vlm: VLMService,
    request: VideoAnalysisRequest,
    source_duration_s: float,
    limits: VideoMemoryLimits = VideoMemoryLimits(),
) -> VideoMemory:
    memory = await vlm.analyze_video(request)
    if isinstance(request, TimestampedFramesAnalysisRequest):
        memory = _reconcile_frame_evidence(memory, request.manifest.frames)
    if isinstance(request, TimestampedFramesAnalysisRequest):
        memory = memory.model_copy(
            update={
                "analysis_mode": AnalysisMode.SINGLE_REQUEST,
                "sampling_metadata": SamplingMetadata(
                    requested_fps=_manifest_fps(request.manifest),
                    sampled_frame_count=len(request.manifest.frames),
                    source_duration_s=request.manifest.duration_s,
                    batch_count=1,
                ),
            }
        )
        frame_ids = {frame.frame_id for frame in request.manifest.frames}
        expected_mode = AnalysisMode.SINGLE_REQUEST
    else:
        memory = reconcile_native_video_evidence(memory)
        memory = memory.model_copy(update={"analysis_mode": AnalysisMode.NATIVE_VIDEO})
        frame_ids = None
        expected_mode = AnalysisMode.NATIVE_VIDEO
    return validate_video_memory(
        memory,
        source_duration_s=source_duration_s,
        source_frame_ids=frame_ids,
        expected_analysis_mode=expected_mode,
        limits=limits,
    )


async def analyze_rolling_batches(
    *,
    vlm: VLMService,
    request: TimestampedFramesAnalysisRequest,
    batch_size: int,
    overlap: int,
    max_batches: int,
    final_frame_limit: int,
    limits: VideoMemoryLimits = VideoMemoryLimits(),
) -> VideoMemory:
    if batch_size <= 0 or max_batches <= 0 or final_frame_limit <= 0:
        raise ValueError("rolling batch limits must be positive")
    if overlap < 0 or overlap >= batch_size:
        raise ValueError("overlap must be non-negative and smaller than batch_size")

    batches = _frame_batches(request.manifest.frames, batch_size, overlap)
    if len(batches) > max_batches:
        raise VideoMemoryError(
            "ROLLING_BATCH_LIMIT_EXCEEDED",
            f"rolling analysis needs {len(batches)} batches; maximum is {max_batches}",
        )

    batch_memories: list[VideoMemory] = []
    prior_memory: VideoMemory | None = None
    for index, batch in enumerate(batches):
        batch_manifest = build_sequence_manifest(
            frames=_reindex_frames(batch),
            source_video_uri=request.manifest.source_video_uri,
            duration_s=request.manifest.duration_s,
        )
        prompt = _batch_prompt(request.prompt, index, len(batches), prior_memory)
        memory = await vlm.analyze_video(
            TimestampedFramesAnalysisRequest(
                incident_id=request.incident_id,
                prompt=prompt,
                manifest=batch_manifest,
            )
        )
        memory = _reconcile_frame_evidence(memory, batch)
        memory = memory.model_copy(update={"analysis_mode": AnalysisMode.SINGLE_REQUEST})
        validate_video_memory(
            memory,
            source_duration_s=request.manifest.duration_s,
            source_frame_ids={frame.frame_id for frame in batch},
            expected_analysis_mode=AnalysisMode.SINGLE_REQUEST,
            limits=limits,
        )
        batch_memories.append(memory)
        prior_memory = memory

    representatives = _representative_frames(request.manifest.frames, final_frame_limit)
    synthesis_request = TimestampedFramesAnalysisRequest(
        incident_id=request.incident_id,
        prompt=_synthesis_prompt(request.prompt, batch_memories),
        manifest=build_sequence_manifest(
            frames=_reindex_frames(representatives),
            source_video_uri=request.manifest.source_video_uri,
            duration_s=request.manifest.duration_s,
        ),
    )
    memory = await vlm.analyze_video(synthesis_request)
    memory = _reconcile_frame_evidence(memory, request.manifest.frames)
    memory = memory.model_copy(
        update={
            "analysis_mode": AnalysisMode.ROLLING_BATCHES,
            "sampling_metadata": SamplingMetadata(
                requested_fps=_manifest_fps(request.manifest),
                sampled_frame_count=len(request.manifest.frames),
                source_duration_s=request.manifest.duration_s,
                batch_count=len(batches),
            ),
        }
    )
    return validate_video_memory(
        memory,
        source_duration_s=request.manifest.duration_s,
        source_frame_ids={frame.frame_id for frame in request.manifest.frames},
        expected_analysis_mode=AnalysisMode.ROLLING_BATCHES,
        limits=limits,
    )


def validate_video_memory(
    memory: VideoMemory,
    *,
    source_duration_s: float,
    source_frame_ids: set[str] | None = None,
    expected_analysis_mode: AnalysisMode | None = None,
    limits: VideoMemoryLimits = VideoMemoryLimits(),
) -> VideoMemory:
    """Reject semantically invalid model output without repairing or clamping it."""
    window = memory.incident_window
    if window.t_end > source_duration_s:
        raise VideoMemoryError("VLM_TIMESTAMP_OUT_OF_RANGE", "incident window exceeds source duration")
    if expected_analysis_mode is not None and memory.analysis_mode != expected_analysis_mode:
        raise VideoMemoryError("VLM_ANALYSIS_MODE_INVALID", "analysis mode does not match workflow path")
    if len(memory.tracked_entities) > limits.max_entities:
        raise VideoMemoryError("VLM_ENTITY_LIMIT_EXCEEDED", "VideoMemory contains too many entities")
    if len(memory.timeline) > limits.max_timeline_events:
        raise VideoMemoryError("VLM_TIMELINE_LIMIT_EXCEEDED", "VideoMemory contains too many timeline events")
    if len(memory.claims) > limits.max_claims:
        raise VideoMemoryError("VLM_CLAIM_LIMIT_EXCEEDED", "VideoMemory contains too many claims")

    _require_unique([item.entity_id for item in memory.tracked_entities], "entity IDs")
    _require_unique([item.claim_id for item in memory.claims], "claim IDs")
    evidence_ids = [evidence.evidence_id for claim in memory.claims for evidence in claim.evidence]
    _require_unique(evidence_ids, "evidence IDs")
    if any(not claim.evidence for claim in memory.claims):
        raise VideoMemoryError("VLM_CLAIM_EVIDENCE_MISSING", "every claim must contain frame evidence")

    for timestamp in [
        *(item for item in [memory.representative_timestamp_s] if item is not None),
        *(item.timestamp_s for item in memory.timeline),
        *(item.timestamp_s for item in memory.claims if item.timestamp_s is not None),
        *(evidence.timestamp_s for claim in memory.claims for evidence in claim.evidence),
    ]:
        if timestamp > source_duration_s:
            raise VideoMemoryError("VLM_TIMESTAMP_OUT_OF_RANGE", "VideoMemory timestamp exceeds source duration")
    if memory.representative_timestamp_s is not None and not (
        window.t_start <= memory.representative_timestamp_s <= window.t_end
    ):
        raise VideoMemoryError(
            "VLM_REPRESENTATIVE_TIMESTAMP_INVALID",
            "representative timestamp must be inside the incident window",
        )

    _validate_evidence_references(memory)
    if source_frame_ids is not None and not set(evidence_ids).issubset(source_frame_ids):
        raise VideoMemoryError("VLM_SOURCE_FRAME_INVALID", "VideoMemory references frames outside its input")
    return memory


def merge_video_memory_patch(
    memory: VideoMemory,
    patch: VideoMemoryPatch,
    *,
    reconcile_native_evidence: bool = False,
) -> VideoMemory:
    if patch.base_revision != memory.revision:
        raise VideoMemoryError("VLM_PATCH_REVISION_CONFLICT", "patch base revision does not match current memory")
    current_claims = {claim.claim_id: claim for claim in memory.claims}
    missing_targets = set(patch.target_claim_ids) - set(current_claims)
    if missing_targets:
        raise VideoMemoryError("VLM_PATCH_TARGET_MISSING", "patch targets claims not present in current memory")
    patch_claims = {claim.claim_id: claim for claim in patch.claims}
    for claim_id in patch.target_claim_ids:
        if claim_id in patch_claims:
            current_claims[claim_id] = patch_claims[claim_id]

    handles = _merge_by_id(memory.remote_media_handles, patch.remote_media_handles, "name")
    merged = memory.model_copy(
        update={
            "claims": list(current_claims.values()),
            "remote_media_handles": handles,
            "revision": memory.revision + 1,
        }
    )
    if reconcile_native_evidence:
        merged = reconcile_native_video_evidence(merged)
    evidence_ids = [evidence.evidence_id for claim in merged.claims for evidence in claim.evidence]
    _require_unique(evidence_ids, "evidence IDs")
    if any(not claim.evidence for claim in merged.claims):
        raise VideoMemoryError("VLM_CLAIM_EVIDENCE_MISSING", "every claim must contain frame evidence")
    _validate_evidence_references(merged)
    return merged


def reconcile_native_video_evidence(memory: VideoMemory) -> VideoMemory:
    """Make native-video timestamp evidence internally consistent without frame IDs."""
    if not memory.claims:
        timeline = [event.model_copy(update={"evidence_ids": []}) for event in memory.timeline]
        return memory.model_copy(update={"timeline": timeline})

    claimed_ids: set[str] = set()
    claims = []
    for claim in memory.claims:
        evidence = []
        for item in claim.evidence:
            if item.evidence_id in claimed_ids:
                continue
            evidence.append(item)
            claimed_ids.add(item.evidence_id)
        if not evidence:
            base_id = f"native-evidence:{claim.claim_id}"
            evidence_id = base_id
            suffix = 2
            while evidence_id in claimed_ids:
                evidence_id = f"{base_id}:{suffix}"
                suffix += 1
            evidence = [
                EvidenceReference(
                    evidence_id=evidence_id,
                    timestamp_s=claim.timestamp_s if claim.timestamp_s is not None else memory.incident_window.t0,
                )
            ]
            claimed_ids.add(evidence_id)
        claims.append(claim.model_copy(update={"evidence": evidence}))

    for event in memory.timeline:
        for evidence_id in event.evidence_ids:
            if evidence_id in claimed_ids:
                continue
            target = min(
                range(len(claims)),
                key=lambda index: abs(
                    (claims[index].timestamp_s if claims[index].timestamp_s is not None else memory.incident_window.t0)
                    - event.timestamp_s
                ),
            )
            claims[target] = claims[target].model_copy(
                update={
                    "evidence": [
                        *claims[target].evidence,
                        EvidenceReference(evidence_id=evidence_id, timestamp_s=event.timestamp_s),
                    ]
                }
            )
            claimed_ids.add(evidence_id)

    return memory.model_copy(update={"claims": claims})


def reconcile_video_memory_patch_evidence(
    patch: VideoMemoryPatch,
    frames: list[TimestampedFrame],
    *,
    fallback_timestamp_s: float,
) -> VideoMemoryPatch:
    """Canonicalize frame evidence aliases returned by a focused reanalysis call."""
    frames_by_id = {frame.frame_id: frame for frame in frames}
    evidence_by_id = {item.evidence_id: item for claim in patch.claims for item in claim.evidence}
    items = patch.claims
    reference_timestamps: dict[str, list[float]] = {}
    for item in items:
        if item.timestamp_s is None:
            continue
        for evidence_id in [evidence.evidence_id for evidence in item.evidence]:
            reference_timestamps.setdefault(evidence_id, []).append(item.timestamp_s)

    all_ids = set(evidence_by_id)
    id_mapping: dict[str, str] = {}
    for evidence_id in all_ids:
        if evidence_id in frames_by_id:
            canonical_id = evidence_id
        else:
            evidence = evidence_by_id.get(evidence_id)
            timestamp_s = evidence.timestamp_s if evidence is not None else None
            if timestamp_s is None and reference_timestamps.get(evidence_id):
                timestamp_s = sum(reference_timestamps[evidence_id]) / len(reference_timestamps[evidence_id])
            target_timestamp_s = timestamp_s if timestamp_s is not None else fallback_timestamp_s
            canonical_id = min(frames, key=lambda item: abs(item.timestamp_s - target_timestamp_s)).frame_id
        id_mapping[evidence_id] = canonical_id

    def canonical_ids(values: list[str]) -> list[str]:
        return list(dict.fromkeys(id_mapping.get(value, value) for value in values if value in id_mapping))

    claims = [
        claim.model_copy(
            update={
                "evidence": [
                    EvidenceReference(evidence_id=evidence_id, timestamp_s=frames_by_id[evidence_id].timestamp_s)
                    for evidence_id in canonical_ids([item.evidence_id for item in claim.evidence])
                ]
            }
        )
        for claim in patch.claims
    ]
    return patch.model_copy(update={"claims": claims})


def _frame_batches(frames: list[TimestampedFrame], batch_size: int, overlap: int) -> list[list[TimestampedFrame]]:
    batches = []
    start = 0
    while start < len(frames):
        end = min(start + batch_size, len(frames))
        batches.append(frames[start:end])
        if end == len(frames):
            break
        start = end - overlap
    return batches


def _reindex_frames(frames: list[TimestampedFrame]) -> list[TimestampedFrame]:
    output = []
    previous_timestamp = None
    for index, frame in enumerate(frames):
        delta = 0.0 if previous_timestamp is None else frame.timestamp_s - previous_timestamp
        output.append(frame.model_copy(update={"sequence_index": index, "delta_from_previous_s": delta}))
        previous_timestamp = frame.timestamp_s
    return output


def _representative_frames(frames: list[TimestampedFrame], limit: int) -> list[TimestampedFrame]:
    if len(frames) <= limit:
        return frames
    if limit == 1:
        return [frames[len(frames) // 2]]
    indexes = [round(index * (len(frames) - 1) / (limit - 1)) for index in range(limit)]
    return [frames[index] for index in indexes]


def _reconcile_frame_evidence(memory: VideoMemory, frames: list[TimestampedFrame]) -> VideoMemory:
    """Canonicalize evidence to supplied frames and attach every timeline reference to a claim."""
    frames_by_id = {frame.frame_id: frame for frame in frames}
    evidence_by_id = {item.evidence_id: item for claim in memory.claims for item in claim.evidence}
    reference_timestamps: dict[str, list[float]] = {}
    items = [*memory.timeline, *memory.claims]
    for item in items:
        timestamp_s = getattr(item, "timestamp_s", None)
        if timestamp_s is None:
            continue
        evidence_ids = (
            item.evidence_ids if isinstance(item, TimelineEvent) else [evidence.evidence_id for evidence in item.evidence]
        )
        for evidence_id in evidence_ids:
            reference_timestamps.setdefault(evidence_id, []).append(timestamp_s)

    all_ids = {
        *evidence_by_id,
        *(evidence_id for item in memory.timeline for evidence_id in item.evidence_ids),
    }
    id_mapping: dict[str, str] = {}
    fallback_timestamp_s = (
        memory.representative_timestamp_s
        if memory.representative_timestamp_s is not None
        else memory.incident_window.t0
    )
    for evidence_id in all_ids:
        if evidence_id in frames_by_id:
            canonical_id = evidence_id
        else:
            evidence = evidence_by_id.get(evidence_id)
            timestamp_s = evidence.timestamp_s if evidence is not None else None
            if timestamp_s is None and reference_timestamps.get(evidence_id):
                timestamp_s = sum(reference_timestamps[evidence_id]) / len(reference_timestamps[evidence_id])
            target_timestamp_s = timestamp_s if timestamp_s is not None else fallback_timestamp_s
            frame = min(frames, key=lambda item: abs(item.timestamp_s - target_timestamp_s))
            canonical_id = frame.frame_id
        id_mapping[evidence_id] = canonical_id

    def canonical_ids(values: list[str]) -> list[str]:
        return list(dict.fromkeys(id_mapping[value] for value in values if value in id_mapping))

    timeline = [item.model_copy(update={"evidence_ids": canonical_ids(item.evidence_ids)}) for item in memory.timeline]
    claims = [
        claim.model_copy(
            update={
                "evidence": [
                    EvidenceReference(evidence_id=evidence_id, timestamp_s=frames_by_id[evidence_id].timestamp_s)
                    for evidence_id in canonical_ids([item.evidence_id for item in claim.evidence])
                ]
            }
        )
        for claim in memory.claims
    ]
    claimed_ids = {evidence.evidence_id for claim in claims for evidence in claim.evidence}
    for event in timeline:
        for evidence_id in event.evidence_ids:
            if evidence_id in claimed_ids or not claims:
                continue
            target = min(
                range(len(claims)),
                key=lambda index: abs((claims[index].timestamp_s or event.timestamp_s) - event.timestamp_s),
            )
            claims[target] = claims[target].model_copy(
                update={
                    "evidence": [
                        *claims[target].evidence,
                        EvidenceReference(evidence_id=evidence_id, timestamp_s=frames_by_id[evidence_id].timestamp_s),
                    ]
                }
            )
            claimed_ids.add(evidence_id)
    return memory.model_copy(
        update={
            "timeline": timeline,
            "claims": claims,
        }
    )


def _batch_prompt(
    base: PromptEnvelope,
    index: int,
    total: int,
    prior_memory: VideoMemory | None,
) -> PromptEnvelope:
    compact = _compact_memory(prior_memory) if prior_memory else None
    suffix = json.dumps(
        {"batch_index": index, "batch_count": total, "prior_compact_memory": compact},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return base.model_copy(
        update={
            "text": f"{base.text}\nPhân tích batch tuần tự {index + 1}/{total}. Context: {suffix}",
            "context": {**base.context, "rolling_batch_index": index, "rolling_batch_count": total},
        }
    )


def _synthesis_prompt(base: PromptEnvelope, memories: list[VideoMemory]) -> PromptEnvelope:
    compact_memories = [_compact_memory(memory) for memory in memories]
    suffix = json.dumps(compact_memories, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return base.model_copy(
        update={
            "text": (
                f"{base.text}\nTổng hợp một VideoMemory cuối cùng cho toàn bộ video từ các batch memory theo "
                f"thứ tự thời gian này. Hợp nhất sự kiện trùng ở vùng overlap mà không bịa thêm sự thật. Toàn bộ "
                f"nội dung mô tả phải bằng tiếng Việt: {suffix}"
            ),
            "context": {**base.context, "synthesis_batch_count": len(memories)},
        }
    )


def _compact_memory(memory: VideoMemory) -> dict[str, object]:
    return {
        "global_scene": memory.global_scene,
        "video_summary": memory.video_summary,
        "incident_window": memory.incident_window.model_dump(mode="json"),
        "representative_timestamp_s": memory.representative_timestamp_s,
        "timeline": [item.model_dump(mode="json") for item in memory.timeline],
        "claims": [item.model_dump(mode="json") for item in memory.claims],
    }


def _manifest_fps(manifest: VideoSequenceManifest) -> float:
    positive_deltas = [frame.delta_from_previous_s for frame in manifest.frames if frame.delta_from_previous_s > 0]
    if positive_deltas:
        return 1 / positive_deltas[0]
    return max(len(manifest.frames) / manifest.duration_s, 0.001)


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise VideoMemoryError("VLM_DUPLICATE_ID", f"VideoMemory contains duplicate {label}")


def _validate_evidence_references(memory: VideoMemory) -> None:
    known_evidence_ids = {evidence.evidence_id for claim in memory.claims for evidence in claim.evidence}
    referenced_evidence_ids = {
        evidence_id
        for item in memory.timeline
        for evidence_id in item.evidence_ids
    }
    if not referenced_evidence_ids.issubset(known_evidence_ids):
        raise VideoMemoryError("VLM_EVIDENCE_REFERENCE_INVALID", "VideoMemory references unknown evidence IDs")


def _merge_by_id(
    current: list[MemoryItem],
    updates: list[MemoryItem],
    field: str,
) -> list[MemoryItem]:
    merged = {getattr(item, field): item for item in current}
    merged.update({getattr(item, field): item for item in updates})
    return list(merged.values())
