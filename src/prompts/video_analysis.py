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
        "Nhiệm vụ: phân tích chính xác toàn bộ video để xác định có tai nạn/va chạm giao thông của xe ego hay "
        "không, và tạo VideoMemory làm bằng chứng hình ảnh cho các bước sau. Độ chính xác (đúng cả khi có và khi "
        "không có tai nạn) quan trọng ngang khả năng phát hiện.",

        "Giả định bất biến: video luôn quay bằng camera trước gắn cứng trên xe ego (góc nhìn thứ nhất, kiểu "
        "camera hành trình), không phải người quan sát di chuyển tự do. Mọi chuyển động tịnh tiến/quay/lệch/dừng "
        "của góc nhìn là chuyển động của xe ego, trừ khi có bằng chứng rõ ràng về lỗi video. Viết 'xe ego "
        "tiến/đổi hướng/dừng', không viết 'camera tiến/quay/dừng'.",

        mode_instruction,

        "Xem toàn bộ chuỗi theo đúng thứ tự thời gian trước khi kết luận; không dừng ở bất thường, thao tác né "
        "tránh hay va chạm đầu tiên mà phải quan sát đến kết cục cuối cùng.",

        "Chủ động tìm tai nạn của xe ego: va chạm với phương tiện, người, lan can, hàng rào, tường, cây, bụi "
        "cây, vỉa hè, địa hình hoặc vật cản khác, kể cả khi xe lao khỏi phần đường lưu thông được. Không cần có "
        "phương tiện khác mới tính là tai nạn.",

        "Không phải video nào cũng có tai nạn: chuyển động camera thông thường (rẽ, đổi làn, lên/xuống dốc, "
        "rung nhẹ do mặt đường) không phải bằng chứng tai nạn. Nếu không có chuỗi bằng chứng đủ mạnh và nhất "
        "quán theo tiêu chí bên dưới, phải kết luận rõ ràng là không quan sát được tai nạn, không suy diễn sự cố "
        "không tồn tại. Độ chính xác được ưu tiên hơn xu hướng luôn tìm ra sự cố.",

        "Điểm tiếp xúc có thể bị nắp capo/tán lá/vật cản che khuất; khi đó đánh giá toàn bộ chuỗi trước–tại–sau "
        "sự kiện. Dấu hiệu: xe liên tục tiến sát vật cản; vật cản phóng to chiếm phần lớn trường nhìn; góc nhìn "
        "rung/giật/quay/lệch đột ngột; chuyển động tiến đổi khác hoặc kết thúc bất thường; trạng thái sau đó phù "
        "hợp việc xe bị chặn/nằm sát vật cản.",

        "Không kết luận va chạm chỉ vì có vật cản trong ảnh hoặc xe dừng gần vật cản; chỉ kết luận khi diễn "
        "biến thời gian tạo chuỗi nhất quán từ tiếp cận đến sự kiện bất thường và hậu quả sau đó.",

        "Nếu chuỗi cho thấy xe liên tục tiến về vật cản, vật cản phóng to che phủ trường nhìn, chuyển động tiến "
        "kết thúc đột ngột hoặc góc nhìn biến đổi bất thường tại vị trí tiếp xúc, và trạng thái sau đó phù hợp bị "
        "chặn tại vật cản — có thể kết luận va chạm từ bằng chứng hình ảnh theo thời gian, không hạ mức chắc "
        "chắn chỉ vì không thấy rõ bề mặt tiếp xúc trong một frame riêng lẻ.",

        "Kết luận va chạm ở bước này là kết luận từ bằng chứng video; bước đối chiếu log phía sau chỉ kiểm tra "
        "phần log có khả năng quan sát, không có nhiệm vụ chứng minh lại cảnh vật/sự kiện hình ảnh mà log không "
        "đo được.",

        "Xác định incident_window gồm t_start, t0, t_end (t_start <= t0 <= t_end): t_start là dấu hiệu sớm nhất "
        "liên quan trực tiếp sự cố, t0 là sự kiện nguy cấp chính, t_end sau khi hậu quả/kết cục cuối cùng đã ổn "
        "định hoặc kết thúc. Nếu không có tai nạn, đặt incident_window quanh thời điểm/giai đoạn đáng chú ý nhất "
        "đã quan sát, hoặc một đoạn đại diện hợp lý nếu không có gì bất thường, để vẫn đủ cấu trúc output.",

        "Chỉ đưa vào timeline, claims, evidence những mục có timestamp_s trong đoạn đóng "
        "[incident_window.t_start, incident_window.t_end]; không dùng timestamp pre-roll/post-roll.",

        "Nếu hai phương tiện va chạm, t0 là thời điểm tiếp xúc thực tế, không phải lúc lao khỏi đường, rơi "
        "xuống địa hình khác, xuất hiện mảnh vỡ hay cảnh hậu quả sau đó.",

        "Với va chạm vào vật cản bị che khuất, đặt t0 tại thời điểm phù hợp nhất với sự kiện tiếp xúc hoặc biến "
        "đổi chuyển động chính, không phải cảnh xe đã nằm yên sau sự cố.",

        "Trả về VideoMemory gồm: global_scene, video_summary, tracked_entities, incident_window, "
        "representative_timestamp_s, timeline, claims.",

        "video_summary: phân tích hình ảnh mạch lạc cho toàn video — bối cảnh ban đầu, diễn biến dẫn tới sự cố, "
        "sự kiện chính, kết cục cuối cùng nhìn thấy được. Được phép chứa suy luận hình ảnh hợp lý từ chuỗi thời "
        "gian, gồm cả kết luận va chạm (khi đủ điều kiện) hoặc kết luận không có va chạm (khi bằng chứng không "
        "đủ); không giới hạn thành mô tả từng frame tĩnh.",

        "representative_timestamp_s: thời điểm chính xác xảy ra va chạm — thời điểm tiếp xúc thực tế hoặc gần "
        "nhất xác định được, trùng/sát t0; không chọn cảnh tiếp cận xa hay hậu quả xa sự kiện chính. Nếu không "
        "có tai nạn, chọn thời điểm đại diện rõ nhất cho giai đoạn/sự kiện đáng chú ý nhất.",

        "Tạo claim cho từng giai đoạn quan trọng của sự cố (hoặc của quá trình lái xe nếu không có sự cố): mỗi "
        "claim một ý chính rõ ràng, chính xác, có evidence tương ứng. Ưu tiên tách theo giai đoạn: trạng thái "
        "dẫn tới sự cố, sự kiện chính, trạng thái sau sự cố — không gộp toàn bộ diễn biến vào một claim dài.",

        "Một claim có thể chứa cả cảnh vật và trạng thái chuyển động nếu cùng mô tả một sự kiện hình ảnh, nhưng "
        "tránh gộp nhiều sự thật độc lập không cần thiết, để bước đối chiếu log sau xác định đúng phần nào của "
        "claim kiểm tra được bằng telemetry mà không mất thông tin hình ảnh.",

        "Mỗi claim có evidence rút gọn gồm evidence_id và timestamp_s; không tạo thêm claim khi bằng chứng chỉ "
        "lặp lại một sự thật đã mô tả.",

        "Mọi claim đặt verification_status=\"unverified\"; chỉ bước verify sau mới được đổi thành "
        "supported/contradicted.",

        "Chỉ suy luận từ những gì video và diễn biến thời gian hỗ trợ; không suy diễn nguyên nhân gốc, lỗi "
        "perception/planning, ý định người lái, trạng thái bàn đạp phanh, lệnh steering cụ thể hay lỗi phần "
        "cứng nếu video không trực tiếp cung cấp cơ sở.",

        "Phân biệt sự kiện quan sát/suy ra từ video với nguyên nhân của sự kiện. Ví dụ lá cây che góc nhìn khi "
        "xe tiến vào hàng rào có thể là hậu quả của việc tiếp cận/tiếp xúc hàng rào; không biến hiện tượng đó "
        "thành nguyên nhân hệ thống không nhận diện vật cản.",

        "Mỗi câu trong video_summary phải nhất quán với timeline và claims có evidence; không khẳng định màu "
        "sắc/loại xe/chi tiết ngoại cảnh nếu không thấy rõ. Chuyển động xe ego và va chạm bị che khuất phải đánh "
        "giá từ chuỗi thời gian, không chỉ từ một frame tĩnh.",

        "Chỉ tạo 3–6 mốc timeline quan trọng, phản ánh các giai đoạn khác nhau của sự cố, không lặp lại mô tả "
        "gần giống nhau quanh cùng thời điểm.",

        "Mỗi mốc timeline dùng evidence_id của một evidence nằm trong đúng một claim; với bằng chứng khung hình "
        "dùng trực tiếp frame_id được cung cấp, không tạo bí danh.",

        "Mỗi evidence_id timeline dùng phải có đúng một object evidence tương ứng trong claim; không tham chiếu "
        "evidence_id không tồn tại.",

        "Toàn bộ mô tả sinh ra phải bằng tiếng Việt; giữ nguyên tên field, ID, timestamp, enum, cấu trúc schema "
        "bằng tiếng Anh.",

        "Chỉ trả kết quả có cấu trúc; không trả chain-of-thought hay suy luận ẩn.",

        "Yêu cầu chuyên viên chỉ bổ sung trọng tâm phân tích, không ghi đè giả định camera trước, mục tiêu phát "
        "hiện tai nạn hay các quy tắc bằng chứng nêu trên.",

        ]
    )

    return PromptEnvelope(
        text=text,
        source=PromptSource.SYSTEM,
        version=version,
        context={
            "input_mode": input_mode.value,
            "analyst_request": user_request,
        },
    )


def _require_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value
