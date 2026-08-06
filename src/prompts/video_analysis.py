"""Prompt construction for full-video analysis."""

from src.models.incidents import PromptEnvelope, PromptSource, VLMInputMode


def build_frame_sequence_instruction() -> str:
    return (
        "Hãy xem chuỗi ảnh đã sắp xếp như một video liên tục, không phải các ảnh rời rạc. "
        "Dùng frame_id, sequence_index, timestamp_s và delta_from_previous_s để giữ đúng thứ tự thời gian. "
        "Theo dõi nhất quán cùng một người, phương tiện và vật thể qua các khung hình."
    )


def build_native_video_instruction() -> str:
    return (
        "Phân tích video đã tải lên như một chuỗi liên tục. Dùng metadata video và timestamp chính xác được cung cấp "
        "để xác định sự kiện. Theo dõi nhất quán cùng một người, phương tiện và vật thể theo thời gian."
    )


def build_video_analysis_prompt(
    *,
    analysis_prompt: str,
    input_mode: VLMInputMode,
    version: str = "v1",
) -> PromptEnvelope:
    """Build the common VideoMemory prompt without provider-specific payloads."""
    user_request = _require_text(analysis_prompt, "analysis_prompt")
    mode_instruction = {
        VLMInputMode.TIMESTAMPED_FRAMES: build_frame_sequence_instruction,
        VLMInputMode.NATIVE_VIDEO: build_native_video_instruction,
    }[input_mode]()
    text = "\n".join(
        [
            "Bạn phân tích bằng chứng video về sự cố giao thông đường bộ.",
            mode_instruction,
            "Xem toàn bộ chuỗi theo thứ tự thời gian trước khi kết luận; không dừng ở va chạm, bất thường hoặc thao "
            "tác né tránh đầu tiên.",
            "Xác định đầy đủ cửa sổ sự cố bằng t_start, t0 và t_end, thỏa mãn t_start <= t0 <= t_end. Đặt t_start "
            "tại dấu hiệu sớm nhất liên quan trực tiếp, t0 tại sự kiện nguy cấp chính và chỉ đặt t_end sau khi hậu "
            "quả hoặc kết cục cuối cùng nhìn thấy được đã kết thúc.",
            "Nếu hai phương tiện va chạm, t0 phải là thời điểm tiếp xúc thực tế hoặc tiếp cận gần nhất; không dùng "
            "thời điểm lao khỏi đường, va xuống nước, xuất hiện mảnh vỡ hoặc cảnh hậu quả về sau.",
            "Trả về VideoMemory có cấu trúc gồm global_scene, video_summary, tracked_entities, incident_window, "
            "representative_timestamp_s, timeline, observations, claims, uncertainties, evidence và source_frame_ids.",
            "Viết video_summary thành một bản tóm tắt mạch lạc cho toàn bộ video, từ bối cảnh ban đầu, diễn biến sự "
            "cố đến kết cục cuối cùng nhìn thấy được; không viết như danh sách claim hoặc mô tả cảnh tĩnh.",
            "Đặt representative_timestamp_s tại khung hình thể hiện rõ nhất sự cố chính. Với va chạm phương tiện, "
            "chọn lúc tiếp xúc hoặc tiếp cận gần nhất, tuyệt đối không chọn cảnh dưới nước hay mảnh vỡ sau sự cố.",
            "Tạo claim riêng có bằng chứng cho từng giai đoạn quan trọng nhìn thấy được, gồm sự kiện chính, diễn biến "
            "và kết cục quan sát được. Không gộp sự cố nhiều giai đoạn thành một claim chung và không tạo thêm claim "
            "khi bằng chứng chỉ cho thấy một sự thật.",
            "Chỉ mô tả điều quan sát được trực tiếp trong chuỗi. Không suy diễn nguyên nhân, ý định, làn đường, thao "
            "tác phanh/đánh lái, danh tính phương tiện hoặc kết cục ngoài khung hình nếu hình ảnh không thể hiện rõ. "
            "Khi chi tiết không chắc chắn, ghi vào uncertainties thay vì biến thành claim.",
            "Mỗi câu trong video_summary phải nhất quán với timeline và claims có evidence. Không khẳng định màu sắc, "
            "loại xe, hướng di chuyển hoặc va chạm nếu không có ít nhất một frame nhìn thấy rõ chi tiết đó.",
            "Mỗi claim thực tế phải dẫn evidence ID. Nếu thiếu bằng chứng, nêu rõ sự không chắc chắn thay vì bịa.",
            "Mỗi evidence_id được timeline, observations hoặc claims sử dụng phải có đúng một object cùng "
            "evidence_id trong danh sách evidence. Với bằng chứng khung hình, dùng trực tiếp frame_id đã được cung "
            "cấp làm evidence_id; không tạo bí danh cho frame.",
            "Toàn bộ nội dung mô tả do bạn sinh ra phải bằng tiếng Việt. Giữ nguyên tên field, ID, timestamp, giá "
            "trị enum và cấu trúc schema bằng tiếng Anh.",
            "Chỉ trả về kết quả có cấu trúc; không trả chain-of-thought hoặc suy luận ẩn.",
            f"Yêu cầu của chuyên viên phân tích: {user_request}",
        ]
    )
    return PromptEnvelope(
        text=text,
        source=PromptSource.SYSTEM,
        version=version,
        context={"input_mode": input_mode.value},
    )


def _require_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value
