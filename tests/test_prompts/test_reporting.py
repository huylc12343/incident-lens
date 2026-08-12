from src.models.incidents import (
    AnalysisMode,
    Claim,
    EvidenceReference,
    IncidentWindow,
    RemoteMediaHandle,
    SamplingMetadata,
    VideoMemory,
    VLMProvider,
)
from src.prompts.reporting import build_report_prompt


def _video_memory_with_private_provider_data() -> VideoMemory:
    return VideoMemory(
        global_scene="A road scene",
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


def test_report_prompt_only_requests_three_model_owned_fields() -> None:
    prompt = build_report_prompt(incident_id="INC-001", video_memory=_video_memory_with_private_provider_data())

    assert "field tường thuật" in prompt.text
    assert "timeline, video_observations, hypothesized_causes" in prompt.text
    assert "Không sinh summary, log_findings, alignment, evidence_ids" in prompt.text
    assert "Toàn bộ nội dung bằng tiếng Việt" in prompt.text
    assert "trạng thái review" in prompt.text


def test_report_prompt_excludes_provider_handles_and_artifact_locations() -> None:
    prompt = build_report_prompt(incident_id="INC-001", video_memory=_video_memory_with_private_provider_data())
    serialized = prompt.model_dump_json()

    assert "remote_media_handles" not in prompt.context
    assert "sampling_metadata" not in prompt.context
    assert "private://" not in serialized
    assert "files/private-name" not in serialized
    assert prompt.context["claims"][0]["evidence"][0]["evidence_id"] == "frame-1"


def test_report_prompt_is_deterministic() -> None:
    memory = _video_memory_with_private_provider_data()

    assert build_report_prompt(incident_id="INC-001", video_memory=memory) == build_report_prompt(
        incident_id="INC-001",
        video_memory=memory,
    )
