import pytest

from src.models.incidents import PromptSource, VLMInputMode
from src.prompts.video_analysis import (
    build_frame_sequence_instruction,
    build_native_video_instruction,
    build_video_analysis_prompt,
)


@pytest.mark.parametrize(
    ("mode", "expected_instruction"),
    [
        (VLMInputMode.TIMESTAMPED_FRAMES, "chuỗi ảnh đã sắp xếp"),
        (VLMInputMode.NATIVE_VIDEO, "video đã tải lên"),
    ],
)
def test_video_analysis_prompt_selects_mode_instruction(
    mode: VLMInputMode,
    expected_instruction: str,
) -> None:
    prompt = build_video_analysis_prompt(
        analysis_prompt="Identify the main traffic incident.",
        input_mode=mode,
        version="video-v2",
    )

    assert expected_instruction in prompt.text
    assert "t_start <= t0 <= t_end" in prompt.text
    assert "camera trước gắn cứng trên xe ego" in prompt.text
    assert "trước–tại–sau" in prompt.text
    assert "representative_timestamp_s" in prompt.text
    assert "VideoMemory" in prompt.text
    assert "vlm_has_accident" in prompt.text
    assert "tracked_entities" not in prompt.text
    assert "Timeline gồm 3–6 mốc quan trọng của toàn bộ video" in prompt.text
    assert "[0, video_duration]" in prompt.text
    # The window must stay tight around the incident.
    assert "Không kéo t_start về đầu video hoặc t_end tới cuối video" in prompt.text
    assert 'verification_status="unverified"' in prompt.text
    # The model returns no evidence; the backend maps frames itself.
    assert "Với mỗi claim chỉ trả claim_id, text, timestamp_s, verification_status" in prompt.text
    assert "không trả chain-of-thought" in prompt.text
    assert "Identify the main traffic incident." not in prompt.text
    assert prompt.source == PromptSource.SYSTEM
    assert prompt.version == "video-v2"
    assert prompt.context == {
        "input_mode": mode.value,
        "analyst_request": "Identify the main traffic incident.",
    }


def test_video_analysis_prompt_is_deterministic() -> None:
    kwargs = {
        "analysis_prompt": "Analyze consistently.",
        "input_mode": VLMInputMode.TIMESTAMPED_FRAMES,
    }

    assert build_video_analysis_prompt(**kwargs) == build_video_analysis_prompt(**kwargs)
    assert build_frame_sequence_instruction() == build_frame_sequence_instruction()
    assert build_native_video_instruction() == build_native_video_instruction()


def test_video_analysis_prompt_keeps_no_incident_window_schema_valid() -> None:
    prompt = build_video_analysis_prompt(
        analysis_prompt="Xác định có tai nạn hay không.",
        input_mode=VLMInputMode.NATIVE_VIDEO,
    )

    # With no incident the window must still satisfy IncidentWindow's t_end > 0 schema
    # constraint, which the prompt achieves by pinning t_end to the video duration.
    assert "incident_window.t_start=0" in prompt.text
    assert "incident_window.t0=0" in prompt.text
    assert "incident_window.t_end=video_duration" in prompt.text


def test_video_analysis_prompt_treats_log_hint_as_attention_only() -> None:
    hint = (
        "Attention hint từ telemetry — chỉ gợi ý thời điểm cần xem kỹ, không phải bằng chứng:\n"
        "- Tại giây thứ 12.5: ga giảm đột ngột; phanh tăng đột ngột."
    )
    prompt = build_video_analysis_prompt(
        analysis_prompt="Phân tích toàn bộ diễn biến.",
        input_mode=VLMInputMode.NATIVE_VIDEO,
        log_attention_hint=hint,
    )

    assert prompt.context["log_attention_hint"] == hint
    # The hint may only steer attention; it can never stand in for visual evidence.
    assert "không phải evidence" in prompt.text
    assert "chỉ ghi sự kiện nếu video thực sự hỗ trợ" in prompt.text


def test_video_analysis_rejects_blank_analyst_request() -> None:
    with pytest.raises(ValueError, match="analysis_prompt must not be blank"):
        build_video_analysis_prompt(analysis_prompt="  ", input_mode=VLMInputMode.NATIVE_VIDEO)
