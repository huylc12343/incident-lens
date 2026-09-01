# Privacy và video redaction

## 1. Phạm vi bảo vệ

VLens có thể nhận video hành trình chứa khuôn mặt, biển số và thông tin vị trí/thời gian từ telemetry. Redaction hiện tập trung vào hai loại dữ liệu hình ảnh có khả năng định danh:

- Biển số phương tiện.
- Khuôn mặt xuất hiện trong video.

Telemetry, video gốc, frame và incident clip vẫn có thể chứa dữ liệu nhạy cảm ngoài hai nhóm trên. Vì vậy redaction hình ảnh không thay thế chính sách truy cập, lưu giữ và xóa dữ liệu.

## 2. Pipeline hiện có

Khi `VIDEO_REDACTION_ENABLED=true` (giá trị mặc định), pipeline trong `src/services/detect_and_blur.py` chạy cục bộ trên bản video đã chuẩn hóa trước khi video được gửi tới VLM bên ngoài:

1. Hai model YOLO cục bộ phát hiện biển số và khuôn mặt.
2. Bounding box được mở rộng và giới hạn trong kích thước frame.
3. Tracker vận tốc hằng số nối các frame nằm giữa hai lần detection và chỉ giữ track trong khoảng thời gian giới hạn.
4. Gaussian blur với kernel thích nghi theo kích thước ROI được áp dụng lên từng frame đầu ra.
5. Video đã redaction trở thành đầu vào native-video cho Qwen/DashScope VLM.

Các cấu hình chính:

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `VIDEO_REDACTION_ENABLED` | `true` | Bật hoặc tắt redaction trước khi gọi VLM. |
| `REDACTION_IMAGE_SIZE` | `512` | Kích thước inference YOLO; tăng có thể cải thiện khả năng phát hiện nhưng làm xử lý chậm hơn. |
| `REDACTION_DETECTION_FPS` | `5.0` | Số lần chạy detector trên mỗi giây video; tracker nối các frame ở giữa. |

Nếu tắt `VIDEO_REDACTION_ENABLED`, video đã chuẩn hóa nhưng chưa làm mờ có thể được gửi tới provider AI bên ngoài. Đây là thay đổi trust boundary và chỉ nên thực hiện khi người vận hành hiểu rõ chính sách dữ liệu áp dụng.

## 3. Lưu trữ và chia sẻ

- Video upload và telemetry được lưu trong local upload storage trong quá trình xử lý.
- Frame, chart, evidence và incident clip được lưu trong local artifact storage và có thể được tham chiếu từ incident/report.
- Workflow state và báo cáo terminal được lưu trong SQLite; SQLite không tự mã hóa nội dung ở cấp ứng dụng.
- LangSmith là tùy chọn cho tracing. Không gửi raw video, Base64 media, secret, API key hoặc dữ liệu định danh vào trace/log.
- Chỉ chia sẻ artifact sau khi đã kiểm tra trực quan bản redacted và giới hạn quyền truy cập theo nhu cầu công việc.

Repository chưa chứng minh encryption at rest, authentication/authorization production, external object storage có policy retention hoặc cơ chế xóa dữ liệu theo yêu cầu. Đây là giới hạn của MVP.

## 4. Trạng thái CV benchmark

Repository đã có bộ annotation tại [`eval/cv_benchmark/annotations.json`](../eval/cv_benchmark/annotations.json) và hướng dẫn tại [`eval/cv_benchmark/README.md`](../eval/cv_benchmark/README.md).

Phạm vi hiện tại:

- Lấy mẫu mỗi frame thứ 10, bắt đầu từ frame 1, trên hai video nguồn đi kèm.
- Có **12 vùng biển số** được gán nhãn thủ công: 7 vùng trong video `bridge` và 5 vùng trong video `intersection`.
- Không có khuôn mặt đủ rõ trong hai video nguồn, nên mẫu số face recall bằng 0 và face recall phải ghi là `N/A`.
- Annotation là tập tối thiểu phục vụ regression và so sánh trước/sau; không phải bộ xác nhận privacy ở mức production.

Chưa có artifact kết quả chạy detector hoặc báo cáo precision/recall tổng hợp được commit cùng annotation. Do đó project **chưa tuyên bố plate recall, face recall hoặc mức ẩn danh đạt một ngưỡng cụ thể**.

Trước khi dùng ở mức production, cần bổ sung ít nhất 100–200 frame được gán nhãn độc lập, bao phủ biển số và khuôn mặt ở nhiều khoảng cách/góc nhìn, che khuất, chuyển động nhanh, đêm và mưa; sau đó lưu version model, cấu hình, prediction và metric có thể tái lập.

## 5. Giới hạn và rủi ro còn lại

- Detector có thể bỏ sót đối tượng nhỏ, mờ, che khuất, xuất hiện ngắn hoặc ngoài miền dữ liệu huấn luyện.
- Khi detector chỉ chạy ở một số frame, đối tượng xuất hiện rồi biến mất hoàn toàn giữa hai lần detection sẽ không được tracker định vị.
- Tracker chỉ nối miss ngắn và có thể dự đoán ROI lệch khi chuyển động thay đổi nhanh.
- Blur làm giảm khả năng nhận diện nhưng không chứng minh ẩn danh tuyệt đối hoặc chống khôi phục trong mọi trường hợp.
- Redaction chỉ xử lý khuôn mặt và biển số; logo, địa điểm, giọng nói hoặc metadata vẫn có thể tiết lộ danh tính.
- Bộ test Video/CV gần nhất bị lỗi collection do xung đột cài đặt OpenCV; trạng thái này được ghi trong [`docs/EVALUATION.md`](EVALUATION.md) và không được coi là test pass.

## 6. Checklist vận hành

- Giữ `VIDEO_REDACTION_ENABLED=true` khi gửi video tới provider ngoài.
- Kiểm tra trực quan video redacted trước khi chia sẻ hoặc demo.
- Không commit video riêng tư, secret hoặc dữ liệu định danh không cần thiết.
- Giới hạn thời gian lưu video upload và artifact theo mục đích xử lý.
- Ghi nhận model/config khi chạy benchmark để kết quả có thể tái lập.
- Không công bố recall hoặc cam kết ẩn danh khi chưa có artifact benchmark phù hợp.
