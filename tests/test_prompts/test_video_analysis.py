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
    assert "toàn bộ chuỗi theo thứ tự thời gian" in prompt.text
    assert "kết cục cuối cùng nhìn thấy được" in prompt.text
    assert "Tạo claim riêng có bằng chứng" in prompt.text
    assert "video_summary thành một bản tóm tắt mạch lạc" in prompt.text
    assert "representative_timestamp_s" in prompt.text
    assert "không chọn cảnh dưới nước" in prompt.text
    assert "phải có đúng một object" in prompt.text
    assert "nội dung mô tả do bạn sinh ra phải bằng tiếng Việt" in prompt.text
    assert "VideoMemory" in prompt.text
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
