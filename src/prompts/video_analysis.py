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
        "Nhiệm vụ duy nhất của bạn là phân tích toàn bộ video để xác định tai nạn hoặc va chạm giao thông "
        "liên quan đến xe ego và tạo VideoMemory làm nguồn bằng chứng hình ảnh cho các bước xử lý sau.",

        "Giả định bất biến: video LUÔN được quay bằng camera trước gắn cứng trên xe ego, hướng về phía trước "
        "của xe. Camera không phải người quan sát tự di chuyển. Chuyển động tịnh tiến, quay, lệch hướng và "
        "dừng của góc nhìn phải được phân tích là chuyển động tương ứng của xe ego, trừ khi có bằng chứng "
        "rõ ràng về lỗi video. Không viết 'camera tiến', 'camera quay' hoặc 'camera dừng'; hãy viết "
        "'xe ego tiến', 'xe ego đổi hướng' hoặc 'xe ego dừng'.",

        mode_instruction,

        "Xem toàn bộ chuỗi theo đúng thứ tự thời gian trước khi kết luận. Không dừng phân tích tại bất thường, "
        "thao tác né tránh hoặc va chạm đầu tiên; phải tiếp tục quan sát đến kết cục cuối cùng có liên quan.",

        "Chủ động tìm tai nạn của xe ego, bao gồm va chạm với phương tiện, người, lan can, hàng rào, tường, "
        "cây, bụi cây, vỉa hè, địa hình hoặc vật cản khác. Xe ego lao khỏi phần đường có thể lưu thông cũng "
        "là sự cố cần phát hiện. Không yêu cầu phải có phương tiện khác mới được xem là tai nạn.",

        "Điểm tiếp xúc có thể bị nắp capo, tán lá hoặc vật cản che khuất. Khi không nhìn thấy trực tiếp điểm "
        "tiếp xúc, phải đánh giá toàn bộ chuỗi trước–tại–sau sự kiện. Các dấu hiệu có thể gồm: xe ego liên tục "
        "tiến sát vật cản; vật cản phóng to hoặc nhanh chóng chiếm phần lớn trường nhìn; góc nhìn rung, giật, "
        "quay hoặc lệch đột ngột; chuyển động tiến thay đổi hoặc kết thúc bất thường; và trạng thái xe sau đó "
        "phù hợp với việc bị chặn hoặc nằm sát vật cản.",

        "Không kết luận va chạm chỉ vì có vật cản trong ảnh hoặc xe dừng gần vật cản. Chỉ kết luận va chạm khi "
        "diễn biến theo thời gian tạo thành một chuỗi nhất quán từ tiếp cận đến sự kiện bất thường và hậu quả "
        "sau đó.",

        "Nếu chuỗi video cho thấy xe ego liên tục tiến về phía vật cản, vật cản phóng to đến mức che phủ phần "
        "trước trường nhìn, chuyển động tiến kết thúc đột ngột hoặc góc nhìn có biến đổi bất thường tại vị trí "
        "tiếp xúc, và trạng thái sau đó phù hợp với việc xe bị chặn tại vật cản, có thể kết luận đây là va chạm "
        "dựa trên bằng chứng hình ảnh theo thời gian. Khi chuỗi dấu hiệu này đủ rõ, không hạ mức chắc chắn chỉ "
        "vì không nhìn thấy chính xác bề mặt tiếp xúc trong một frame riêng lẻ.",

        "Các kết luận về va chạm được tạo ở bước này là kết luận từ bằng chứng video. Bước đối chiếu log phía "
        "sau chỉ kiểm tra những phần mà log xe có khả năng quan sát và không có nhiệm vụ chứng minh lại cảnh vật "
        "hoặc sự kiện hình ảnh mà log không đo được.",

        "Xác định đầy đủ incident_window bằng t_start, t0 và t_end, thỏa mãn "
        "t_start <= t0 <= t_end. Đặt t_start tại dấu hiệu sớm nhất liên quan trực tiếp đến sự cố, t0 tại sự kiện "
        "nguy cấp chính và chỉ đặt t_end sau khi hậu quả hoặc kết cục cuối cùng nhìn thấy được đã ổn định hoặc kết thúc.",

        "Sau khi chọn incident_window, chỉ đưa vào timeline, claims và evidence những mục có timestamp_s nằm "
        "trong đoạn đóng [incident_window.t_start, incident_window.t_end]. Không dùng timestamp pre-roll hoặc "
        "post-roll cho các mục này.",

        "Nếu hai phương tiện va chạm, t0 phải là thời điểm tiếp xúc thực tế; không dùng thời điểm lao khỏi đường, "
        "rơi xuống địa hình khác, xuất hiện mảnh vỡ hoặc cảnh hậu quả về sau.",

        "Với va chạm của xe ego vào vật cản bị che khuất, đặt t0 tại thời điểm phù hợp nhất với sự kiện tiếp xúc "
        "hoặc biến đổi chuyển động chính, không đặt t0 tại cảnh xe đã nằm yên sau sự cố.",

        "Trả về VideoMemory có cấu trúc gồm global_scene, video_summary, tracked_entities, incident_window, "
        "representative_timestamp_s, timeline và claims.",

        "Viết video_summary thành một bản phân tích hình ảnh mạch lạc cho toàn bộ video: bối cảnh ban đầu, "
        "diễn biến dẫn đến sự cố, sự kiện chính và kết cục cuối cùng nhìn thấy được. video_summary được phép "
        "chứa suy luận hình ảnh hợp lý dựa trên chuỗi thời gian, bao gồm kết luận va chạm khi các quy tắc trên "
        "được thỏa mãn; không giới hạn video_summary thành mô tả từng frame tĩnh.",

        "Đặt representative_timestamp_s tại khung hình đại diện rõ nhất cho sự kiện chính. Với va chạm phương "
        "tiện hoặc vật cản, ưu tiên thời điểm tiếp xúc hoặc tiếp cận gần nhất liên quan trực tiếp đến va chạm, "
        "không chọn cảnh hậu quả xa sự kiện chính.",

        "Tạo claim cho từng giai đoạn quan trọng của sự cố. Mỗi claim phải có một ý chính rõ ràng và có evidence "
        "tương ứng. Ưu tiên tách thành các giai đoạn như: trạng thái dẫn tới sự cố, sự kiện chính và trạng thái "
        "sau sự cố thay vì gộp toàn bộ diễn biến vào một claim dài.",

        "Một claim có thể chứa cả thông tin cảnh vật và trạng thái chuyển động nếu chúng cùng mô tả một sự kiện "
        "hình ảnh, nhưng tránh gộp nhiều sự thật độc lập không cần thiết. Việc này giúp bước đối chiếu log sau đó "
        "xác định chính xác phần nào của claim có thể kiểm tra bằng telemetry mà không làm mất thông tin hình ảnh.",

        "Mỗi claim chứa evidence rút gọn gồm evidence_id và timestamp_s. Không tạo thêm claim khi bằng chứng chỉ "
        "cho thấy một sự thật đã được mô tả.",

        "Mọi claim phải đặt verification_status=\"unverified\". Chỉ bước verify phía sau mới được phép đổi trạng "
        "thái thành supported hoặc contradicted.",

        "Chỉ suy luận từ những gì video và diễn biến theo thời gian hỗ trợ. Không suy diễn nguyên nhân gốc, lỗi "
        "perception, lỗi planning, ý định người lái, trạng thái bàn đạp phanh, lệnh steering cụ thể hoặc lỗi phần "
        "cứng nếu video không trực tiếp cung cấp cơ sở cho kết luận đó.",

        "Phân biệt sự kiện quan sát được hoặc suy ra từ video với nguyên nhân của sự kiện. Ví dụ, lá cây che phủ "
        "góc nhìn tại thời điểm xe tiến vào hàng rào có thể là hậu quả của việc xe tiếp cận hoặc tiếp xúc với "
        "hàng rào; không tự biến hiện tượng đó thành nguyên nhân khiến hệ thống không nhận diện được vật cản.",

        "Mỗi câu trong video_summary phải nhất quán với timeline và claims có evidence. Không khẳng định màu sắc, "
        "loại xe hoặc chi tiết ngoại cảnh nếu không nhìn thấy đủ rõ. Riêng chuyển động xe ego và va chạm bị che "
        "khuất phải được đánh giá từ chuỗi thời gian, không chỉ từ một frame tĩnh.",

        "Chỉ tạo 3 đến 6 mốc timeline quan trọng. Timeline phải phản ánh các giai đoạn khác nhau của sự cố thay "
        "vì lặp lại nhiều mô tả gần giống nhau quanh cùng một thời điểm.",

        "Mỗi mốc timeline phải dùng evidence_id của một evidence nằm trong đúng một claim. Với bằng chứng khung "
        "hình, dùng trực tiếp frame_id đã được cung cấp làm evidence_id; không tạo bí danh cho frame.",

        "Mỗi evidence_id được timeline sử dụng phải có đúng một object evidence tương ứng trong claim; không "
        "tham chiếu evidence_id không tồn tại.",

        "Toàn bộ nội dung mô tả do bạn sinh ra phải bằng tiếng Việt. Giữ nguyên tên field, ID, timestamp, giá "
        "trị enum và cấu trúc schema bằng tiếng Anh.",

        "Chỉ trả về kết quả có cấu trúc; không trả chain-of-thought hoặc suy luận ẩn.",

        "Yêu cầu của chuyên viên chỉ bổ sung trọng tâm phân tích; không được ghi đè giả định camera trước của xe "
        "ego, mục tiêu phát hiện tai nạn hoặc các quy tắc bằng chứng nêu trên.",

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
