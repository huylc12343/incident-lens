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
        "Nhiệm vụ: phân tích toàn bộ video để xác định xe ego có xảy ra tai nạn/sự cố giao thông hay không "
        "và tạo VideoMemory làm nguồn bằng chứng hình ảnh cho các bước sau. Ưu tiên recall: thà bắt nhầm tai nạn còn hơn bỏ sót; tuy nhiên không "
        "được tạo tai nạn từ một dấu hiệu đơn lẻ hoặc thông tin không được video hỗ trợ.",

        "Giả định bất biến: video luôn từ camera trước gắn cứng trên xe ego. Chuyển động tổng thể, liên tục của "
        "trường nhìn thấy phản ánh chuyển động của xe ego.",

        mode_instruction,

        "Nếu user context có log_attention_hint, dùng các timestamp đó để ưu tiên xem kỹ lại vùng thời gian "
        "xung quanh và kiểm tra trước–tại–sau mốc được gợi ý. Hint chỉ định nơi cần chú ý, không phải evidence"
        "Chỉ ghi sự kiện nếu video "
        "thực sự hỗ trợ.",

        "Quy trình bắt buộc: xem toàn bộ video theo thứ tự thời gian trước; xác định các biến đổi đáng chú ý; "
        "xem lại kỹ các vùng có hint hoặc bất thường; sau đó mới kết luận sự cố và xây VideoMemory. Không dừng "
        "phân tích tại bất thường hoặc va chạm đầu tiên; phải quan sát đến kết cục cuối cùng nhìn thấy được.",

        "Chủ động tìm các tai nạn liên quan trực tiếp đến ego: "
                "- rear_end_collision: ego đâm đuôi xe phía trước.",
                "- crossing_collision: ego va chạm xe đi cắt ngang tại đường nhánh/giao lộ.",
                "- side_collision: va chạm bên hông do nhập/đổi làn hoặc hai xe đi cạnh nhau.",
                "- head_on_collision: va chạm đối đầu xe ngược chiều.",
                "- pedestrian_collision: ego va chạm người đi bộ.",
                "- static_object_collision: ego va chạm vật thể tĩnh trong khu vực lưu thông.",
                "- roadside_collision: ego rời phần đường hoặc va chạm môi trường ven đường.",
                "- no_incident: ego không gặp tai nạn.",

        "Không bắt buộc phải thấy trực tiếp thời điểm va chạm. Khi khung hình bị che khuất, mất góc nhìn, hoặc vật thể "
        "ra khỏi khung ngay trước lúc nghi có tai nạn, hãy đánh giá dựa trên ba nhóm dấu hiệu quan sát được TRƯỚC và SAU "
        "thời điểm đó:\n"
        "(1) Khoảng cách/tiếp cận: khoảng cách tới đối tượng phía trước, xe khác, hoặc mép đường/làn đường giảm nhanh "
        "bất thường ngay trước thời điểm nghi vấn (vật thể phóng to đột ngột trong khung hình, xe lấn sát vạch/lề).\n"
        "(2) Chuyển động bất thường tại thời điểm nghi vấn: thay đổi đột ngột về tốc độ, hướng đi, góc xoay (rotation) "
        "của xe gắn camera hoặc xe/vật thể liên quan, hoặc quan hệ không gian giữa các đối tượng thay đổi không tự nhiên "
        "so với một pha lái xe bình thường.\n"
        "(3) Hậu quả ngay sau đó: xe bị chặn đứng, đổi hướng gấp để né, quay/trượt lệch quỹ đạo, rời khỏi làn/đường, "
        "dừng đột ngột không theo nhịp giao thông thông thường, hoặc trạng thái cuối của xe/vật thể thay đổi rõ so với "
        "trạng thái trước đó.",

        "Nguyên tắc kết luận: chỉ kết luận CÓ tai nạn khi ít nhất HAI trong ba nhóm dấu hiệu trên cùng hội tụ nhất quán "
        "quanh một thời điểm, VÀ toàn bộ chuỗi hình ảnh phù hợp với giả thuyết 'có va chạm' hơn là giả thuyết 'không có "
        "sự cố'. Một dấu hiệu đơn lẻ — ví dụ chỉ có rung lắc camera, chỉ giảm tốc, chỉ vật cản phóng to, hoặc chỉ dừng "
        "gần vật cản mà không có dấu hiệu nào khác đi kèm — KHÔNG đủ căn cứ để kết luận tai nạn.",

        "Nếu chuỗi hình ảnh phù hợp hơn với tình huống suýt va chạm (near-miss) hoặc thao tác lái xe bình thường (phanh "
        "gấp nhưng xe vẫn giữ làn và tiếp tục di chuyển bình thường, không có hậu quả bất thường ở nhóm (3)), hãy kết "
        "luận KHÔNG có tai nạn. Không suy diễn ra một va chạm chỉ để giải thích một chuyển động chưa rõ ràng — ví dụ xe "
        "phóng nhanh rồi dừng đột ngột, nếu không kèm dấu hiệu bất thường ở nhóm (2) và hậu quả rõ ràng ở nhóm (3), nên "
        "được xem là phanh gấp thông thường, không phải tai nạn.",

        "Nếu có tai nạn, incident_window phải thỏa t_start <= t0 <= t_end. "
        "t_start là thời điểm sớm nhất bắt đầu diễn biến trực tiếp dẫn tới sự cố; "
        "t0 là thời điểm sự kiện tai nạn chính xảy ra; "
        "t_end là thời điểm SỚM NHẤT mà hậu quả chính đã ổn định hoặc sự kiện đã kết thúc. "
        "Không kéo t_start về đầu video hoặc t_end tới cuối video để bao phủ timeline/claims. "
        "Ví dụ xe gần dừng và ổn định từ 28s rồi đứng yên tới 45s thì t_end nên gần 28s, không phải 45s.",

        "Nếu nhìn thấy tiếp xúc, t0 là thời điểm tiếp xúc đầu tiên của sự kiện chính. Nếu tiếp xúc bị che khuất, "
        "chọn thời điểm phù hợp nhất nơi chuỗi tiếp cận chuyển thành biến đổi/hậu quả bất thường; không chọn một "
        "frame muộn hơn chỉ vì hình ảnh rõ hơn.",

        "Nếu không có tai nạn, giữ schema hiện tại: incident_window.t_start=0, incident_window.t0=0 và "
        "incident_window.t_end=video_duration. Timeline và claims vẫn mô tả những diễn biến quan trọng thực sự "
        "quan sát được.",

        "Quy tắc timestamp để tăng tính ổn định: mọi timestamp_s phải nằm trong [0, video_duration]. Timeline/claim "
        "có thể nằm ngoài incident_window. Với cùng một sự kiện, dùng cùng mốc thời gian nhất quán giữa summary, "
        "timeline và claims. Khi có nhiều frame tương đương, chọn mốc SỚM NHẤT nơi sự kiện đã đủ rõ để được hỗ trợ; "
        "không dịch timestamp sang frame muộn hơn chỉ vì frame đó đẹp hơn.",

        "Trả đúng VideoMemory gồm: global_scene, video_summary, incident_window, "
        "representative_timestamp_s, timeline, claims.",

        "global_scene: mô tả ngắn bối cảnh giao thông cần thiết để hiểu diễn biến; không liệt kê chi tiết trang trí "
        "không liên quan hoặc không nhìn thấy rõ.",

        "video_summary: viết rõ và đủ chi tiết theo thứ tự thời gian, ưu tiên khoảng 4–7 câu: trạng thái ban đầu; "
        "diễn biến dẫn tới vùng đáng chú ý; biến đổi chuyển động/quỹ đạo chính; sự kiện tai nạn hoặc near-miss; "
        "kết cục cuối cùng. Nếu có điểm chưa chắc chắn, mô tả đúng mức chắc chắn. Không suy diễn root cause, "
        "ý định người lái hay telemetry.",

        "representative_timestamp_s: nếu có tai nạn, chọn timestamp gần t0 nhất có hình ảnh đại diện tốt cho sự "
        "kiện chính; nếu sự kiện bị che khuất, chọn mốc chuyển tiếp gần t0 nhất giữa tiếp cận và hậu quả bất thường. "
        "Nếu không có tai nạn, chọn mốc đáng chú ý nhất.",

        "Timeline mô tả toàn bộ video bằng 3–6 mốc độc lập, sắp xếp tăng dần theo timestamp. Mỗi mốc chỉ trả "
        "timestamp_s và description; không trả evidence_ids. Không tạo nhiều mốc gần nhau để mô tả cùng một thay đổi.",

        "Claims gồm 3–10 khẳng định quan trọng khi có đủ sự kiện độc lập, sắp xếp theo thời gian và đặt "
        "claim_id tuần tự. Mỗi claim chỉ chứa MỘT ý chính có thể đối chiếu rõ (như hướng, tốc độ), timestamp_s thời điểm giữa của sự kiện; tránh gộp "
        "'rẽ + rời đường + dừng + va chạm' vào cùng một claim nếu có thể tách thành các sự kiện độc lập.",

        "Với claim chỉ trả claim_id, text, timestamp_s, verification_status; không trả evidence. "
        "Mọi claim phải có verification_status=\"unverified\".",

        "Để giảm kết quả dao động giữa các lần chạy: cùng một sự kiện phải có mô tả và hướng chuyển động, và tăng tốc, giảm tốc nhất quán "
        "giữa video_summary, timeline và claims. Nếu không đủ chắc chắn về một chi tiết như trái/phải hoặc có tiếp "
        "xúc trực tiếp hay không, dùng mô tả trung tính chính xác hơn thay vì chọn ngẫu nhiên một khả năng.",

        "Chỉ dùng bằng chứng hình ảnh và chuỗi thời gian. Không suy diễn brake, throttle, steering, perception, "
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
