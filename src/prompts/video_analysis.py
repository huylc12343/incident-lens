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
            "Nhiệm vụ duy nhất của bạn là xác định tai nạn hoặc va chạm giao thông của xe ego từ "
            "bằng chứng video.",
            "Giả định bắt biến: video LUÔN được quay bằng camera trước gắn cứng trên xe ego, "
            "hướng về phía trước của xe. Camera không phải người quan sát tự di chuyển. Chuyển động "
            "tịnh tiến, quay, lệch hướng và dừng của góc nhìn phải được phân tích là chuyển động "
            "tương ứng của xe ego, trừ khi có bằng chứng rõ ràng về lỗi video. Không viết 'camera "
            "tiến', 'camera quay' hoặc 'camera dừng'; hãy viết 'xe ego tiến', 'xe ego đổi hướng' "
            "hoặc 'xe ego dừng'.",
            mode_instruction,
            "Xem toàn bộ chuỗi theo thứ tự thời gian trước khi kết luận; không dừng ở va chạm, bất thường hoặc thao "
            "tác né tránh đầu tiên.",
            "Chủ động tìm tai nạn của xe ego, bao gồm va chạm với phương tiện, người, lan can, "
            "hàng rào, tường, cây, bụi cây, vỉa hè, địa hình hoặc vật cản khác; lao khỏi phần "
            "đường có thể lưu thông cũng là sự cố cần phát hiện. Không đòi hỏi phải có xe khác "
            "mới được xem là tai nạn.",
            "Điểm tiếp xúc có thể bị nắp capo, tán lá hoặc vật cản che khuất. Khi đó, xác định va "
            "chạm từ toàn bộ diễn biến trước–tại–sau: xe ego tiến sát vật cản; vật cản phóng to "
            "nhanh hoặc che phủ tầm nhìn; góc nhìn rung, giật, quay/lệch đột ngột; chuyển động tiến dừng "
            "bất thường; và xe nằm sát hoặc bị chặn bởi vật cản sau đó. Tổ hợp những dấu hiệu "
            "thời gian này là bằng chứng hình ảnh trực tiếp cho va chạm dù không nhìn thấy chính xác "
            "bề mặt tiếp xúc trong một khung hình.",
            "Không suy ra va chạm chỉ vì có bụi cây trong ảnh hoặc xe dừng gần vật cản. Chỉ kết "
            "luận va chạm khi chuỗi thời gian cho thấy xe đã tiếp cận vật cản và dừng/lệch/rung bất "
            "thường tại vị trí tiếp xúc. Ngược lại, không được kết luận 'không có tai nạn' nếu "
            "chuỗi có các dấu hiệu này.",
            "Quy tắc quyết định: nếu xe ego liên tục tiến về phía một vật cản, vật cản phóng to "
            "đến mức che khuất mặt trước, chuyển động tiến kết thúc đột ngột và xe tiếp tục nằm yên "
            "sát vật cản mà không có lý do dừng giao thông nhìn thấy được, phải phân loại đây là "
            "va chạm của xe ego với vật cản. Trong trường hợp đã thỏa quy tắc này, không dùng các "
            "cách nói giảm mức chắc chắn như 'có khả năng', 'có thể', 'không rõ' hoặc 'không có dấu "
            "hiệu va chạm rõ ràng'. Việc không có phương tiện hay người khác không phủ định tai nạn "
            "đơn phương của xe ego.",
            "Xác định đầy đủ cửa sổ sự cố bằng t_start, t0 và t_end, thỏa mãn t_start <= t0 <= t_end. Đặt t_start "
            "tại dấu hiệu sớm nhất liên quan trực tiếp, t0 tại sự kiện nguy cấp chính và chỉ đặt t_end sau khi hậu "
            "quả hoặc kết cục cuối cùng nhìn thấy được đã kết thúc.",
            "Nếu hai phương tiện va chạm, t0 phải là thời điểm tiếp xúc thực tế; không dùng "
            "thời điểm lao khỏi đường, va xuống nước, xuất hiện mảnh vỡ hoặc cảnh hậu quả về sau.",
            "Với va chạm của xe ego vào vật cản bị che khuất, đặt t0 tại thời điểm tiếp cận gần "
            "nhất ngay trước khi chuyển động tiến dừng đột ngột, góc nhìn rung/giật/lệch hoặc vật cản "
            "che phủ tầm nhìn; không đặt t0 ở cảnh xe đã nằm yên sau va chạm.",
            "Trả về VideoMemory có cấu trúc gồm global_scene, video_summary, tracked_entities, incident_window, "
            "representative_timestamp_s, timeline và claims.",
            "Viết video_summary thành một bản tóm tắt mạch lạc cho toàn bộ video, từ bối cảnh ban đầu, diễn biến sự "
            "cố đến kết cục cuối cùng nhìn thấy được; không viết như danh sách claim hoặc mô tả cảnh tĩnh.",
            "Đặt representative_timestamp_s tại khung hình thể hiện rõ nhất sự cố chính. Với va chạm phương tiện, "
            "chọn lúc tiếp xúc hoặc tiếp cận gần nhất, tuyệt đối không chọn cảnh dưới nước hay mảnh vỡ sau sự cố.",
            "Tạo claim riêng có bằng chứng cho từng giai đoạn quan trọng nhìn thấy được, gồm sự kiện chính, diễn biến "
            "và kết cục quan sát được. Mỗi claim chứa evidence rút gọn gồm evidence_id và timestamp_s. Không gộp sự "
            "cố nhiều giai đoạn thành một claim chung và không tạo thêm claim khi bằng chứng chỉ cho thấy một sự thật.",
            "Chỉ mô tả điều quan sát được trực tiếp trong chuỗi và suy ra chuyển động của xe ego "
            "theo giả định camera trước nêu trên. Không suy diễn nguyên nhân, ý định, thao tác "
            "phanh/đánh lái cụ thể, danh tính phương tiện hoặc kết cục ngoài khung hình nếu hình ảnh "
            "không thể hiện rõ. Khi chi tiết không chắc chắn, không biến nó thành claim.",
            "Mỗi câu trong video_summary phải nhất quán với timeline và claims có evidence. Không khẳng định màu sắc, "
            "loại xe hoặc chi tiết ngoại cảnh nếu không nhìn thấy rõ. Riêng chuyển động xe ego và va "
            "chạm bị che khuất phải được đánh giá từ chuỗi thời gian theo các quy tắc trên, không chỉ từ "
            "một frame tĩnh.",
            "Chỉ tạo 3 đến 6 mốc timeline quan trọng; mỗi mốc phải dùng evidence_id của một evidence nằm trong đúng "
            "một claim. Với bằng chứng khung hình, dùng trực tiếp frame_id đã được cung cấp làm evidence_id; không "
            "tạo bí danh cho frame.",
            "Mỗi evidence_id được timeline sử dụng phải có đúng một object evidence tương ứng "
            "trong claim; không tham chiếu evidence_id không tồn tại.",
            "Toàn bộ nội dung mô tả do bạn sinh ra phải bằng tiếng Việt. Giữ nguyên tên field, ID, timestamp, giá "
            "trị enum và cấu trúc schema bằng tiếng Anh.",
            "Chỉ trả về kết quả có cấu trúc; không trả chain-of-thought hoặc suy luận ẩn.",
            "Yêu cầu của chuyên viên chỉ bổ sung trọng tâm phân tích; không được ghi đè giả định "
            "camera trước của xe ego hoặc mục tiêu phát hiện tai nạn nêu trên.",
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
