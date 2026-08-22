# Privacy và video redaction

## Biện pháp hiện có

Khi `VIDEO_REDACTION_ENABLED=true`, pipeline `src/services/detect_and_blur.py` phát hiện biển số và khuôn mặt bằng hai trọng số YOLO cục bộ. Pipeline xử lý từng frame, mở rộng bounding box trước khi áp Gaussian blur, và dùng tracker giới hạn thời gian để che phủ trong các miss detector ngắn. Video đã redaction là đầu vào native-video cho VLM.

Các tham số như confidence threshold, kích thước inference, padding, thời gian track và blur kernel đều được cấu hình; tắt cờ này sẽ gửi video đã chuẩn hóa nhưng chưa redaction. Không đưa API key, URL nội bộ, raw media Base64 hay thông tin định danh vào tài liệu này.

## Giới hạn

Redaction phụ thuộc detector và chất lượng video, nên có thể bỏ sót đối tượng nhỏ, che khuất, chuyển động nhanh hoặc ngoài khung hình. Tracker chỉ hỗ trợ miss ngắn và không thay thế detection; blur không chứng minh việc ẩn danh hoàn hảo. Người vận hành cần xác minh artifact redacted trước khi chia sẻ ra ngoài và tuân thủ chính sách dữ liệu áp dụng.

## Benchmark

Quy ước benchmark CV là `eval/cv_benchmark/`: khi được bổ sung, thư mục này nên chứa manifest không nhạy cảm, tiêu chí face/plate recall và artifact/tổng hợp có thể tái lập. **Thư mục này chưa có trong checkout hiện tại**, nên repository chưa thể tuyên bố metric blur/recall đã chạy. Liên kết dự kiến: [`eval/cv_benchmark/`](../eval/cv_benchmark/).

Việc thiếu benchmark là một backlog đánh giá, không phải bằng chứng rằng pipeline redaction thất bại hay đạt một ngưỡng cụ thể.
