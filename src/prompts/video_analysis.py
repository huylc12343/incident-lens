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
    log_attention_hint: str | None = None,
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
            # =========================================================
            # 1. ROLE & OBJECTIVE
            # =========================================================
            "Nhiệm vụ: phân tích toàn bộ video theo thứ tự thời gian để xác định xe ego có xảy ra tai nạn/sự cố "
            "giao thông hay không và tạo VideoMemory làm nguồn bằng chứng hình ảnh cho các bước sau. "
            "Ưu tiên recall khi TÌM vùng nghi vấn: không bỏ sót diễn biến có khả năng là sự cố. "
            "Tuy nhiên quyết định cuối vẫn phải tuân theo tiêu chuẩn bằng chứng bên dưới; không kết luận tai nạn "
            "từ một dấu hiệu đơn lẻ.",

            "Giả định bất biến: video luôn từ camera trước gắn cứng trên xe ego. Chuyển động tổng thể và liên tục "
            "của trường nhìn phản ánh chuyển động của xe ego.",

            mode_instruction,

            # =========================================================
            # 2. ANALYSIS PROCEDURE & ATTENTION HINT
            # =========================================================
            "Nếu user context có log_attention_hint, dùng các timestamp đó để ưu tiên xem kỹ vùng trước–tại–sau "
            "mốc được gợi ý. Hint chỉ là vị trí cần chú ý, không phải evidence; chỉ ghi sự kiện nếu video thực sự hỗ trợ.",

            "Bắt buộc xem toàn bộ video theo thứ tự thời gian đến kết cục cuối cùng. Trước tiên nhận diện các vùng "
            "bất thường hoặc được hint, sau đó xem kỹ chuỗi trước–tại–sau các vùng đó rồi mới kết luận. "
            "Không dừng phân tích tại bất thường hoặc va chạm đầu tiên.",

            # =========================================================
            # 3. INCIDENT TYPES
            # =========================================================
            "Chủ động tìm sự cố liên quan trực tiếp đến ego. Phân loại chi tiết gồm: "
            "rear_end_collision (đâm vào phía sau xe cùng hướng), "
            "crossing_collision (xe cắt ngang quỹ đạo ego), "
            "side_collision (nhập/đổi làn hoặc hai xe gần cùng hướng va chạm bên hông), "
            "head_on_collision (xe ngược chiều đối đầu), "
            "pedestrian_collision (người đi bộ), "
            "static_object_collision (vật thể tĩnh), "
            "roadside_collision (rời đường hoặc môi trường ven đường), "
            "no_incident (không có tai nạn), other_unknown (có tai nạn nhưng không xác định được cơ chế).",

            # =========================================================
            # 4. INCIDENT DECISION
            # =========================================================
            "Quy tắc kết luận tai nạn:\n"
            "- Nếu nhìn thấy rõ tiếp xúc/va chạm vật lý liên quan trực tiếp đến ego, có thể kết luận CÓ tai nạn.\n"
            "- Nếu điểm tiếp xúc không nhìn thấy, bị che khuất hoặc vật thể rời khung ngay trước thời điểm nghi vấn, "
            "đánh giá chuỗi trước–tại–sau theo ba nhóm dấu hiệu:\n"
            "  (1) tiếp cận bất thường: khoảng cách tới xe, người, vật cản hoặc mép đường giảm nhanh;\n"
            "  (2) biến đổi chuyển động bất thường: ego hoặc đối tượng đổi tốc độ, hướng, rotation hoặc quan hệ "
            "không gian đột ngột so với diễn biến bình thường;\n"
            "  (3) hậu quả: dừng bất thường, né gấp, trượt/quay, lệch hoặc rời đường, bị chặn đứng, hoặc trạng thái "
            "cuối thay đổi rõ.\n"
            "Khi không thấy trực tiếp tiếp xúc, chỉ kết luận CÓ tai nạn nếu ít nhất HAI trong ba nhóm trên hội tụ "
            "nhất quán quanh cùng một thời điểm và toàn bộ chuỗi phù hợp với giả thuyết có sự cố hơn là lái xe bình thường.",

            "Một dấu hiệu đơn lẻ như rung camera, giảm tốc, vật cản phóng to hoặc dừng gần vật cản không đủ để kết luận "
            "tai nạn. Nếu chuỗi phù hợp hơn với near-miss, phanh gấp hoặc né tránh bình thường và không xuất hiện hậu quả "
            "bất thường phù hợp với tai nạn, kết luận KHÔNG có tai nạn.",

            # =========================================================
            # 5. TEMPORAL RULES
            # =========================================================
            "Nếu có tai nạn, incident_window phải thỏa t_start <= t0 <= t_end: "
            "t_start là thời điểm sớm nhất bắt đầu diễn biến trực tiếp dẫn tới sự cố; "
            "t0 là thời điểm sự kiện tai nạn chính xảy ra; "
            "t_end là thời điểm SỚM NHẤT hậu quả chính đã ổn định hoặc sự kiện đã kết thúc. "
            "Không kéo t_start về đầu video hoặc t_end tới cuối video chỉ để bao phủ timeline/claims.",

            "Nếu nhìn thấy tiếp xúc, t0 là thời điểm tiếp xúc đầu tiên của sự kiện chính. "
            "Nếu tiếp xúc bị che khuất, t0 là thời điểm phù hợp nhất nơi chuỗi tiếp cận chuyển thành biến đổi hoặc "
            "hậu quả bất thường; không chọn frame muộn hơn chỉ vì hình ảnh rõ hơn.",

            "Nếu không có tai nạn, đặt incident_window.t_start=0, incident_window.t0=0 và "
            "incident_window.t_end=video_duration.",

            "Mọi timestamp_s phải nằm trong [0, video_duration]. Timeline và claims có thể nằm ngoài incident_window. "
            "Với cùng một sự kiện, timestamp và mô tả phải nhất quán giữa video_summary, timeline và claims. "
            "Timestamp của timeline/claim là mốc đại diện tốt nhất cho sự kiện được mô tả; nếu nhiều frame tương đương, "
            "chọn mốc SỚM NHẤT nơi sự kiện đã đủ rõ để được hỗ trợ.",

            "representative_timestamp_s: nếu có tai nạn, chọn frame gần t0 nhất thể hiện tốt sự kiện chính; "
            "nếu t0 bị che khuất, chọn frame gần t0 nhất thể hiện rõ chuyển tiếp từ tiếp cận sang biến đổi/hậu quả. "
            "Nếu không có tai nạn, chọn mốc đáng chú ý nhất của video.",

            # =========================================================
            # 6. VIDEOMEMORY CONTENT
            # =========================================================
            "Trả đúng VideoMemory theo schema hiện tại. vlm_has_accident bắt buộc là true hoặc false theo đánh giá "
            "về việc ego có tai nạn trong video hay không.",

            "global_scene: mô tả ngắn bối cảnh giao thông cần thiết để hiểu diễn biến; bỏ các chi tiết trang trí "
            "không liên quan hoặc không nhìn thấy rõ.",

            "video_summary: mô tả diễn biến theo thứ tự thời gian, ưu tiên 4–7 câu: trạng thái ban đầu; diễn biến dẫn "
            "tới vùng đáng chú ý; biến đổi chuyển động/quỹ đạo chính; tai nạn hoặc near-miss; và kết cục cuối cùng.",

            "Timeline gồm 3–6 mốc quan trọng của toàn bộ video, sắp xếp tăng dần theo timestamp. "
            "Mỗi mốc chỉ chứa timestamp_s và description. Không tạo nhiều mốc gần nhau để mô tả cùng một sự kiện.",

            "Claims gồm các khẳng định quan trọng có bằng chứng hình ảnh rõ, sắp xếp theo thời gian và dùng claim_id "
            "tuần tự. Mỗi claim chỉ chứa MỘT ý chính có thể đối chiếu độc lập; không gộp nhiều hành vi như "
            "'rẽ + rời đường + dừng + va chạm' trong cùng một claim. "
            "Không chia nhỏ hoặc tạo claim đồng nghĩa chỉ để đạt số lượng tối thiểu.",

            "Với mỗi claim chỉ trả claim_id, text, timestamp_s, verification_status. "
            "Mọi claim phải có verification_status=\"unverified\".",

            # =========================================================
            # 7. CONSISTENCY & ANTI-HALLUCINATION
            # =========================================================
            "Giữ nhất quán cùng một sự kiện giữa video_summary, timeline và claims, đặc biệt về hướng chuyển động, "
            "tăng/giảm tốc, việc rời đường và có/không có tiếp xúc. Nếu một chi tiết như trái/phải hoặc tiếp xúc trực tiếp "
            "không đủ chắc chắn, dùng mô tả trung tính chính xác hơn thay vì chọn ngẫu nhiên.",

            "Chỉ sử dụng bằng chứng hình ảnh và chuỗi thời gian. Không suy diễn brake, throttle, steering, perception, "
            "planning, lỗi phần cứng, ý định người lái hoặc nguyên nhân gốc nếu video không trực tiếp hỗ trợ.",

            "Chỉ trả structured output đúng schema; không trả chain-of-thought hoặc giải thích ngoài kết quả.",
        ]
    )


    context = {
        "input_mode": input_mode.value,
        "analyst_request": user_request,
    }
    if log_attention_hint is not None and log_attention_hint.strip():
        context["log_attention_hint"] = log_attention_hint.strip()
    return PromptEnvelope(
        text=text,
        source=PromptSource.SYSTEM,
        version=version,
        context=context,
    )


def _require_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value
