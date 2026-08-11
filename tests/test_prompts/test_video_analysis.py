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
    assert "[incident_window.t_start, incident_window.t_end]" in prompt.text
    assert "Không dùng timestamp pre-roll hoặc post-roll" in prompt.text
    assert "toàn bộ chuỗi theo đúng thứ tự thời gian" in prompt.text
    assert "camera trước gắn cứng trên xe ego" in prompt.text
    assert "Camera không phải người quan sát tự di chuyển" in prompt.text
    assert "Không viết 'camera tiến'" in prompt.text
    assert "bụi cây" in prompt.text
    assert "trước–tại–sau" in prompt.text
    assert "không chỉ từ một frame tĩnh" in prompt.text
    assert "không hạ mức chắc chắn" in prompt.text
    assert "không đặt t0 tại cảnh xe đã nằm yên sau sự cố" in prompt.text
    assert "không được ghi đè giả định camera trước" in prompt.text
    assert "kết cục cuối cùng nhìn thấy được" in prompt.text
    assert "Tạo claim cho từng giai đoạn quan trọng" in prompt.text
    assert "video_summary thành một bản phân tích hình ảnh mạch lạc" in prompt.text
    assert "representative_timestamp_s" in prompt.text
    assert "không chọn cảnh hậu quả xa sự kiện chính" in prompt.text
    assert "phải có đúng một object" in prompt.text
    assert "nội dung mô tả do bạn sinh ra phải bằng tiếng Việt" in prompt.text
    assert "VideoMemory" in prompt.text
    assert 'verification_status="unverified"' in prompt.text
    assert "suy luận ẩn" in prompt.text
    assert prompt.source == PromptSource.SYSTEM
    assert prompt.version == "video-v2"
    assert prompt.context == {"input_mode": mode.value}


def test_video_analysis_prompt_is_deterministic() -> None:
    kwargs = {
        "analysis_prompt": "Analyze consistently.",
        "input_mode": VLMInputMode.TIMESTAMPED_FRAMES,
    }

    assert build_video_analysis_prompt(**kwargs) == build_video_analysis_prompt(**kwargs)
    assert build_frame_sequence_instruction() == build_frame_sequence_instruction()
    assert build_native_video_instruction() == build_native_video_instruction()


def test_video_analysis_rejects_blank_analyst_request() -> None:
    with pytest.raises(ValueError, match="analysis_prompt must not be blank"):
        build_video_analysis_prompt(analysis_prompt="  ", input_mode=VLMInputMode.NATIVE_VIDEO)
