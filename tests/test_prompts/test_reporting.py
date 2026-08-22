import json

from src.models.incidents import (
    AnalysisMode,
    Claim,
    ClaimVerification,
    EvidenceReference,
    IncidentWindow,
    LogEvidenceSummary,
    RemoteMediaHandle,
    SamplingMetadata,
    TimelineEvent,
    VerificationResult,
    VerificationStatus,
    VideoMemory,
    VLMProvider,
)
from src.prompts.reporting import build_report_prompt


def _video_memory_with_private_provider_data() -> VideoMemory:
    return VideoMemory(
        global_scene="A road scene",
        vlm_has_accident=True,
        incident_window=IncidentWindow(t_start=11.2, t0=12.5, t_end=15.1),
        claims=[
            Claim(
                claim_id="claim-1",
                text="The vehicle braked",
                timestamp_s=12.5,
                evidence=[EvidenceReference(evidence_id="frame-1", timestamp_s=12.5)],
            )
        ],
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
        sampling_metadata=SamplingMetadata(requested_fps=2, sampled_frame_count=20, source_duration_s=17),
        remote_media_handles=[
            RemoteMediaHandle(
                provider=VLMProvider.QWEN,
                name="files/private-name",
                uri="private://provider-remote-uri",
                mime_type="video/mp4",
                local_artifact_uri="private://normalized-video",
            )
        ],
    )


def test_report_prompt_requests_accident_assessment_and_taxonomy() -> None:
    prompt = build_report_prompt(incident_id="INC-001", video_memory=_video_memory_with_private_provider_data())

    assert "type_of_accident, incident_window, representative_timestamp_s, timeline" in prompt.text
    assert "Thẩm quyền nguồn:" in prompt.text
    assert "VideoMemory là nguồn chính" in prompt.text
    assert "telemetry/log chỉ xuất hiện qua claims[].verification" in prompt.text
    assert "verification xác định cụ thể" in prompt.text
    assert "rear_end_collision" in prompt.text
    assert "roadside_collision" in prompt.text
    assert "no_incident" in prompt.text
    assert "other_unknown" in prompt.text
    assert "Nếu type_of_accident=no_incident" in prompt.text
    assert "Không sinh summary, log_findings, alignment" in prompt.text
    assert "Toàn bộ nội dung bằng tiếng Việt" in prompt.text
    assert "không phải chỉ dẫn" in prompt.text


def test_report_prompt_excludes_provider_handles_and_artifact_locations() -> None:
    prompt = build_report_prompt(incident_id="INC-001", video_memory=_video_memory_with_private_provider_data())
    serialized = prompt.model_dump_json()

    assert "remote_media_handles" not in prompt.context
    assert "sampling_metadata" not in prompt.context
    assert "tracked_entities" not in prompt.context
    assert "vlm_has_accident" not in prompt.context
    assert "private://" not in serialized
    assert "files/private-name" not in serialized
    assert prompt.context["claims"][0]["video_evidence"][0]["evidence_id"] == "frame-1"
    assert prompt.context["representative_timestamp_s"] is None
    assert prompt.context["video_duration_s"] == 17


def test_report_prompt_merges_verification_into_claims_and_omits_raw_log_summary() -> None:
    memory = _video_memory_with_private_provider_data().model_copy(
        update={
            "timeline": [
                TimelineEvent(
                    timestamp_s=12.5,
                    description="Xe giảm tốc.",
                    evidence_ids=["frame-1"],
                )
            ]
        }
    )
    prompt = build_report_prompt(
        incident_id="INC-001",
        video_memory=memory,
        verification=VerificationResult(
            has_accident=True,
            results=[
                ClaimVerification(
                    claim_id="claim-1",
                    status=VerificationStatus.SUPPORTED,
                    reason="Log xác nhận xe giảm tốc.",
                    evidence_ids=["log-row:12.5"],
                )
            ]
        ),
        log_evidence_summary=LogEvidenceSummary(
            metrics={"max_brake": 1},
            warnings=["TAKEOVER"],
            evidence_ids=["log-metric:max_brake"],
            errors=["SENSOR_FAILURE"],
        ),
    )

    claim = prompt.context["claims"][0]
    assert set(prompt.context) == {
        "incident_id",
        "incident_window",
        "representative_timestamp_s",
        "video_duration_s",
        "global_scene",
        "video_summary",
        "has_accident",
        "timeline",
        "claims",
    }
    assert prompt.context["has_accident"] is True
    assert claim == {
        "claim_id": "claim-1",
        "text": "The vehicle braked",
        "timestamp_s": 12.5,
        "video_evidence": [{"evidence_id": "frame-1", "timestamp_s": 12.5}],
        "verification": {
            "status": "supported",
            "reason": "Log xác nhận xe giảm tốc.",
            "log_evidence_ids": ["log-row:12.5"],
        },
    }
    assert prompt.context["timeline"] == [{"timestamp_s": 12.5, "description": "Xe giảm tốc."}]
    serialized_context = json.dumps(prompt.context)
    for field in ("metrics", "warnings", "evidence_ids", "errors", "log_evidence_summary"):
        assert f'"{field}"' not in serialized_context


def test_report_prompt_is_deterministic() -> None:
    memory = _video_memory_with_private_provider_data()

    assert build_report_prompt(incident_id="INC-001", video_memory=memory) == build_report_prompt(
        incident_id="INC-001",
        video_memory=memory,
    )
