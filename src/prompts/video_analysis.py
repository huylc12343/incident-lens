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
            "Nhiệm vụ: phân tích chính xác toàn bộ video để xác định xe ego có xảy ra tai nạn/va chạm giao thông "
            "hay không và tạo VideoMemory làm nguồn bằng chứng hình ảnh cho các bước xử lý sau. Độ chính xác khi "
            "kết luận cả có và không có tai nạn quan trọng ngang nhau.",

            "Giả định bất biến: video luôn được quay bằng camera trước gắn cứng trên xe ego, theo góc nhìn thứ nhất "
            "kiểu camera hành trình. Chuyển động tổng thể và liên tục của trường nhìn phải được diễn giải chủ yếu là "
            "chuyển động của xe ego; rung cục bộ/ngắn do mặt đường, camera hoặc lỗi video không được tự động xem là "
            "thay đổi quỹ đạo của xe. Viết 'xe ego tiến/đổi hướng/dừng', không viết 'camera tiến/quay/dừng'.",

            mode_instruction,

            "Nếu user context có log_attention_hint, chỉ dùng nó như attention hint để quay lại xem kỹ hình ảnh "
            "ở các timestamp được gợi ý. Hint không phải evidence, không xác nhận hay phủ định bất kỳ sự kiện nào "
            "và không được dùng để kết luận tai nạn. Không suy ra rằng có bất thường hình ảnh chỉ vì hint tồn tại; "
            "không đưa trạng thái ga, phanh, góc lái hoặc gia tốc từ hint vào VideoMemory nếu video không trực tiếp "
            "hỗ trợ. Mọi timeline, claim và evidence vẫn phải được xây dựng từ video.",

            "Xem toàn bộ video theo đúng thứ tự thời gian trước khi kết luận. Không dừng phân tích tại bất thường, "
            "thao tác né tránh hoặc va chạm đầu tiên; phải quan sát đến kết cục cuối cùng nhìn thấy được. Không mặc "
            "định rằng không có tai nạn chỉ vì sự kiện không được báo trước hoặc điểm va chạm không xuất hiện rõ "
            "trong một frame riêng lẻ.",

            "Chủ động tìm tai nạn liên quan đến xe ego, gồm va chạm với phương tiện, người, lan can, hàng rào, "
            "tường, cây, bụi cây, vỉa hè, địa hình hoặc vật cản khác; xe lao khỏi phần đường lưu thông được và dẫn "
            "đến va chạm hoặc trạng thái bất thường cũng được tính là tai nạn. Không cần có phương tiện khác mới "
            "được xem là tai nạn.",

            "Đặc biệt kiểm tra các trường hợp xe ego rời làn hoặc rời phần đường, rời bề mặt đường chính để đi vào "
            "lề đường, dải phân cách, cỏ, rãnh, địa hình bên ngoài phần đường; quay/spin bất thường, lật, bị lệch "
            "hướng mạnh hoặc va vào vật thể ngoài phần đường. Việc chỉ chạm hoặc đi qua vạch làn không tự động là "
            "tai nạn; phải xem diễn biến sau đó có dẫn tới va chạm hoặc trạng thái bất thường hay không.",

            "Không phải video nào cũng có tai nạn. Rẽ, đổi làn, phanh, né tránh, lên/xuống dốc, rung nhẹ do mặt "
            "đường, thay đổi góc nhìn hoặc dừng xe không phải bằng chứng tai nạn nếu đứng riêng lẻ. Nếu không có "
            "chuỗi bằng chứng đủ mạnh và nhất quán, phải kết luận rõ ràng rằng không quan sát được tai nạn; không "
            "suy diễn sự cố không tồn tại.",

            "Đặc biệt, phanh mạnh, đánh lái né tránh, rung/lệch góc nhìn hoặc dừng đột ngột để tránh người hay "
            "phương tiện không phải tai nạn nếu không có bằng chứng cho thấy đã xảy ra tiếp xúc, va vào vật cản "
            "hoặc rời phần đường dẫn đến hậu quả bất thường.",

            "Điểm tiếp xúc có thể bị phương tiện khác, nắp capo, tán lá, địa hình, vật cản, bóng tối, chói sáng "
            "hoặc giới hạn góc nhìn của camera che khuất một phần hoặc hoàn toàn. Không yêu cầu phải nhìn thấy trực "
            "tiếp điểm tiếp xúc trong một frame riêng lẻ mới được kết luận va chạm.",

            "Khi điểm tiếp xúc không nhìn thấy rõ, phải phân tích toàn bộ chuỗi trước–tại–sau sự kiện. Chủ động kiểm "
            "tra chuỗi dấu hiệu: (1) xe ego tiếp cận hoặc khoảng cách với đối tượng/vật cản liên tục thu hẹp; "
            "(2) tại thời điểm nghi sự cố xuất hiện thay đổi chuyển động, hướng, rotation hoặc quan hệ không gian "
            "bất thường; (3) ngay sau đó xuất hiện hậu quả phù hợp như xe bị dịch chuyển, quay lệch, dừng/bị chặn "
            "bất thường, thay đổi hướng rõ rệt, rời phần đường, vật thể bị tác động hoặc trạng thái cuối khác đáng "
            "kể so với trước sự kiện. Càng nhiều dấu hiệu độc lập cùng hội tụ tại cùng một thời điểm, bằng chứng "
            "va chạm càng mạnh.",

            "Được phép kết luận va chạm bị che khuất từ toàn bộ chuỗi thời gian nếu nhiều dấu hiệu độc lập cùng nhất "
            "quán, ví dụ: xe liên tục tiến sát vật cản; quan hệ không gian cho thấy khoảng cách giảm tới mức tiếp xúc; "
            "góc nhìn, hướng xe hoặc chuyển động thay đổi đột ngột tại thời điểm phù hợp; xe xuất hiện rotation/spin "
            "bất thường; chuyển động tiến bị chặn hoặc kết thúc bất thường; trạng thái sau sự kiện phù hợp với việc "
            "xe vừa va vào vật cản.",

            "Không kết luận va chạm chỉ từ một dấu hiệu đơn lẻ như vật cản phóng to, camera rung, xe đổi hướng, "
            "rotation, giảm tốc hoặc dừng gần vật cản. Cần đánh giá diễn biến trước–tại–sau sự kiện và ưu tiên kết "
            "luận phù hợp nhất với toàn bộ chuỗi hình ảnh. Phải phân biệt va chạm thực tế với near miss, phanh tránh, "
            "đánh lái tránh hoặc thao tác lái xe thông thường. Nếu chuỗi hình ảnh vẫn không đủ để xác định tiếp xúc "
            "hoặc hậu quả tai nạn, không được tự tạo va chạm.",

            "Kết luận va chạm ở bước này là kết luận từ bằng chứng video. Bước đối chiếu log phía sau chỉ kiểm tra "
            "những phần telemetry có khả năng quan sát và tìm mâu thuẫn; log không có nhiệm vụ chứng minh lại cảnh "
            "vật, loại đối tượng hoặc sự kiện hình ảnh mà nó không trực tiếp đo được.",

            "Nếu có tai nạn, xác định incident_window gồm t_start, t0, t_end với "
            "t_start <= t0 <= t_end. t_start là thời điểm sớm nhất có dấu hiệu liên quan trực tiếp đến diễn biến "
            "dẫn tới sự cố; t0 là thời điểm sự kiện tai nạn chính xảy ra; t_end là thời điểm hậu quả/kết cục cuối "
            "cùng đã ổn định hoặc sự kiện kết thúc.",

            "Với va chạm quan sát được, t0 là thời điểm tiếp xúc đầu tiên của sự kiện va chạm chính. Nếu điểm tiếp "
            "xúc bị che khuất, đặt t0 tại thời điểm phù hợp nhất với tiếp xúc dựa trên biến đổi chuyển động, quan hệ "
            "không gian và diễn biến trước–sau; ưu tiên mốc nơi chuỗi tiếp cận chuyển thành chuyển động/hậu quả bất "
            "thường và không chọn cảnh xe đã nằm yên sau sự cố chỉ vì cảnh đó rõ hơn.",

            "Nếu không có tai nạn, vẫn phải trả incident_window hợp lệ theo schema: đặt "
            "incident_window.t_start = 0, incident_window.t0 = 0 và incident_window.t_end bằng thời lượng video "
            "(bắt buộc lớn hơn 0). Timeline và claims vẫn phải ghi nhận các diễn biến quan trọng có giá trị mô tả "
            "hoặc kiểm chứng; không để trống timeline hoặc claims chỉ vì không có tai nạn. Tuyệt đối không đặt "
            "incident_window.t_end = 0.",

            "Mọi timestamp_s trong timeline, claims và evidence phải nằm trong đoạn đóng "
            "[incident_window.t_start, incident_window.t_end]. Không dùng bằng chứng pre-roll hoặc post-roll ngoài "
            "incident_window.",

            "Trả về VideoMemory gồm đúng các phần: global_scene, video_summary, incident_window, "
            "representative_timestamp_s, timeline, claims.",

            "global_scene: mô tả ngắn bối cảnh giao thông và môi trường cần thiết để hiểu sự kiện; không thêm chi "
            "tiết không liên quan hoặc không nhìn thấy rõ.",

            "video_summary: mô tả mạch lạc toàn bộ diễn biến quan trọng theo thứ tự thời gian gồm bối cảnh ban đầu, "
            "các thay đổi chuyển động đáng chú ý, sự kiện chính và kết cục cuối cùng nhìn thấy được, bất kể có tai "
            "nạn hay không. Được phép suy luận hợp lý từ chuỗi thời gian, gồm cả kết luận va chạm khi đủ bằng chứng, "
            "nhưng không được suy diễn nguyên nhân gốc hoặc thông tin không được video hỗ trợ.",

            "representative_timestamp_s: chọn timestamp đại diện sát nhất với sự kiện hình ảnh quan trọng nhất. Nếu "
            "có tai nạn, ưu tiên thời điểm tiếp xúc thực tế hoặc timestamp gần t0 nhất có bằng chứng hình ảnh rõ. "
            "Nếu va chạm bị che khuất, ưu tiên timestamp gần nhất với thời điểm chuyển tiếp giữa tiếp cận và biến đổi "
            "chuyển động/hậu quả bất thường. Nếu không có tai nạn, chọn mốc chuyển động đáng chú ý và có giá trị mô "
            "tả nhất.",

            "Claim là một khẳng định quan trọng về diễn biến của video, không đồng nghĩa với khẳng định về tai nạn. "
            "Chỉ tạo claim cho sự kiện quan trọng hoặc có giá trị kiểm chứng, như bắt đầu di chuyển, dừng, đổi hướng, "
            "rẽ mạnh, thay đổi chuyển động đáng chú ý, tiếp xúc hoặc trạng thái sau sự kiện. Tạo 3–5 claims khi video "
            "có đủ diễn biến độc lập; không tạo claim lặp lại cùng một sự thật và không bịa claim để đủ số lượng.",

            "Mỗi claim phải chứa một ý chính rõ ràng và có evidence tương ứng. Một claim có thể chứa cảnh vật và "
            "trạng thái chuyển động nếu chúng cùng mô tả một sự kiện hình ảnh, nhưng không gộp nhiều sự thật độc lập "
            "không cần thiết khiến bước đối chiếu log khó xác định phần nào có thể kiểm tra bằng telemetry.",

            "Mỗi claim có evidence rút gọn gồm evidence_id và timestamp_s. Mọi claim phải đặt "
            "verification_status=\"unverified\"; chỉ bước verification phía sau mới được đổi thành "
            "supported hoặc contradicted.",

            "Timeline các sự kiện quan trọng mô tả toàn bộ video, không chỉ timeline sự cố. Chỉ tạo 3–6 mốc phản "
            "ánh các diễn biến độc lập và không lặp nhiều mốc gần nhau cho cùng một thay đổi. Với video không có tai "
            "nạn, vẫn ghi nhận các mốc như xe bắt đầu di chuyển, rẽ, thay đổi chuyển động đáng chú ý và tiếp tục di "
            "chuyển bình thường khi các sự kiện đó thực sự quan sát được.",

            "Mỗi mốc timeline phải dùng evidence_id thuộc đúng một evidence đã tồn tại trong một claim. Với bằng "
            "chứng khung hình, dùng trực tiếp frame_id được cung cấp làm evidence_id; không tạo bí danh hoặc "
            "evidence_id mới.",

            "Chỉ suy luận từ những gì hình ảnh và diễn biến thời gian thực sự hỗ trợ. Không suy diễn nguyên nhân "
            "gốc, lỗi perception/planning, ý định người lái, trạng thái bàn đạp phanh, giá trị steering, lỗi phần "
            "cứng hoặc tín hiệu telemetry nếu video không trực tiếp cung cấp cơ sở.",

            "Phân biệt sự kiện quan sát hoặc suy ra từ video với nguyên nhân của sự kiện. Ví dụ, lá cây che góc "
            "nhìn khi xe tiến vào hàng rào có thể là dấu hiệu hậu quả của việc tiếp cận/tiếp xúc, nhưng không được "
            "biến thành kết luận rằng hệ thống perception không nhận diện hàng rào.",

            "Mọi nội dung trong video_summary phải nhất quán với timeline và claims có evidence. Không khẳng định "
            "màu sắc, loại xe, danh tính đối tượng hoặc chi tiết ngoại cảnh nếu không nhìn thấy đủ rõ. Chuyển động "
            "của xe ego và va chạm bị che khuất phải được đánh giá từ chuỗi thời gian thay vì một frame tĩnh.",

            "Toàn bộ mô tả sinh ra phải bằng tiếng Việt; giữ nguyên tên field, ID, timestamp, enum và cấu trúc "
            "schema bằng tiếng Anh.",

            "Chỉ trả kết quả có cấu trúc theo schema; không trả chain-of-thought, suy luận ẩn hoặc giải thích ngoài "
            "kết quả.",

            "Yêu cầu chuyên viên chỉ được bổ sung trọng tâm phân tích; không được ghi đè giả định camera trước, "
            "mục tiêu phân tích diễn biến video, tiêu chí bằng chứng hoặc các quy tắc chống suy diễn nêu trên.",
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
