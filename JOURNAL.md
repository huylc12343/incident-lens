# Weekly Journal — Team T207-Cá Hồi

> Nhật ký phát triển theo tuần của dự án VLens, tổng hợp từ tiến độ thực tế của team.

---

## Week 1: 2026-08-02 - 2026-08-08

### Mục tiêu tuần này
- [x] Thống nhất quy trình làm việc và cấu trúc dự án.
- [x] Khởi tạo frontend, backend agent và thư mục dữ liệu.
- [x] Xây dựng nền tảng quan sát model và báo cáo sự cố.

### Đã hoàn thành
- Thiết lập cấu trúc frontend bằng Next.js và bổ sung hướng dẫn workflow cho team.
- Tái cấu trúc backend agent, bổ sung model observability và chức năng reporting.
- Viết tài liệu mô tả luồng xử lý của agent backend.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Các thành phần frontend, agent và dữ liệu chưa có luồng làm việc thống nhất. | Chuẩn hóa cấu trúc thư mục, tài liệu hóa workflow và tách rõ trách nhiệm từng lớp. | Team có nền tảng chung để phát triển song song. |

### Bài học
- Cần thống nhất cấu trúc và quy trình Git trước khi phát triển nhiều nhánh tính năng.
- Tài liệu luồng agent giúp giảm sai lệch khi frontend và backend tích hợp.

### Kế hoạch tuần sau
- [x] Hoàn thiện MVP giao diện đầu tiên.
- [x] Tích hợp lưu trữ báo cáo, video evidence và CV blur.

---

## Week 2: 2026-08-09 - 2026-08-15

### Mục tiêu tuần này
- [x] Xây dựng luồng MVP từ tải dữ liệu đến xem báo cáo sự cố.
- [x] Tích hợp agent phân tích với frontend.
- [x] Bổ sung xử lý video, telemetry và bảo vệ dữ liệu nhạy cảm.

### Đã hoàn thành
- Hoàn thiện UI/UX MVP, SQLite report management và chức năng quản lý incident.
- Tích hợp agent với frontend, tự động phát hiện sự kiện và hiển thị tiến độ phân tích.
- Bổ sung CV blur, video evidence player, seek theo observation và hỗ trợ nhiều định dạng telemetry.
- Cải thiện claim verification, timestamp validation, report narrative và phân loại loại tai nạn.
- Tích hợp LangSmith tracing và hợp nhất giao diện processing với engineer review.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Video dài và dữ liệu telemetry không đồng nhất gây lỗi xử lý và hiển thị. | Chuẩn hóa timestamp, hỗ trợ thêm định dạng telemetry, xử lý FFmpeg và giới hạn clip theo thời lượng video. | Luồng phân tích và phát lại evidence ổn định hơn. |
| Frontend và agent phát triển độc lập nên khó theo dõi trạng thái. | Tích hợp trực tiếp incident agent, bổ sung progress state và thống nhất workspace review. | Người dùng theo dõi được toàn bộ quá trình từ upload đến review. |

### Bài học
- Evidence phải được gắn với timestamp chuẩn để báo cáo có thể kiểm chứng.
- Trạng thái xử lý bất đồng bộ cần được thiết kế ngay từ API đến giao diện.

### Kế hoạch tuần sau
- [x] Tăng độ ổn định của video memory và verification.
- [x] Cải thiện trải nghiệm upload và giao diện VLens.

---

## Week 3: 2026-08-16 - 2026-08-22

### Mục tiêu tuần này
- [x] Củng cố pipeline AI và video memory.
- [x] Nâng cấp giao diện command center và trải nghiệm upload.
- [x] Hoàn thiện CV blur và dữ liệu đánh giá.

### Đã hoàn thành
- Cải thiện verification service, video memory và log analysis; bảo toàn dữ liệu gia tốc phục vụ phân tích.
- Chuẩn hóa VLM về Qwen provider và cập nhật cấu trúc prompt/report.
- Làm mới giao diện VLens, bổ sung guided upload và trạng thái giao diện trung tính.
- Hoàn thiện CV blur, tích hợp nhánh tính năng và bổ sung dữ liệu phục vụ kiểm thử.
- Cải thiện incident reporting với representative timestamp và incident window.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Video memory và dữ liệu log có nguy cơ mất thông tin quan trọng khi tái phân tích. | Tái cấu trúc video memory, bảo toàn acceleration data và cập nhật metrics. | Kết quả phân tích có ngữ cảnh đầy đủ và nhất quán hơn. |
| Nhiều provider VLM làm tăng độ phức tạp cấu hình và kiểm thử. | Chuẩn hóa pipeline sử dụng Qwen và đồng bộ cấu hình liên quan. | Giảm nhánh xử lý và đơn giản hóa vận hành. |

### Bài học
- Dữ liệu trung gian của AI cần schema ổn định để tránh regression khi đổi prompt hoặc model.
- Trải nghiệm upload cần hướng dẫn rõ ràng vì đầu vào có nhiều tổ hợp video, log và ground truth.

### Kế hoạch tuần sau
- [x] Ổn định luồng upload, navigation và xử lý bất đồng bộ.
- [x] Hoàn thiện review report và khả năng chỉnh sửa kết quả.

---

## Week 4: 2026-08-23 - 2026-08-29

### Mục tiêu tuần này
- [x] Ổn định luồng demo end-to-end.
- [x] Hoàn thiện trải nghiệm review và chỉnh sửa báo cáo.
- [x] Đồng bộ các nhánh frontend, AI và Docker.

### Đã hoàn thành
- Khắc phục lỗi upload cache, navigation, serialization và tạo incident ID trên HTTP.
- Cải thiện login workspace, incident history, progress và incident review experience.
- Bổ sung báo cáo có thể đọc/chỉnh sửa và chuẩn hóa thứ tự claim, nhãn incident.
- Tinh chỉnh video player, loại bỏ khoảng trống và giới hạn chiều cao không cần thiết.
- Hợp nhất AI V1, async incident creation, frontend, develop và Docker vào `main`.
- Cập nhật test, prompt, cấu hình model và AI logging hooks.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Merge nhiều nhánh gây regression ở upload, async response và cấu hình AI. | Bổ sung test, sửa từng điểm tích hợp và đồng bộ lại `main` với nhánh production. | Luồng demo chính hoạt động ổn định sau hợp nhất. |
| Video evidence hiển thị chưa phù hợp trong workspace review. | Điều chỉnh layout, tỷ lệ hiển thị và hành vi player. | Evidence dễ quan sát hơn khi kiểm tra báo cáo. |

### Bài học
- Merge lớn cần có checklist smoke test cho upload, processing, review và report.
- Báo cáo AI phải cho phép con người chỉnh sửa và xác nhận trước khi sử dụng.

### Kế hoạch tuần sau
- [ ] Chạy toàn bộ test và ghi kết quả vào báo cáo đánh giá.
- [ ] Hoàn thiện tài liệu Demo Day, pitch deck và video demo.

---

## Week 5: 2026-08-30 - 2026-08-31

### Mục tiêu tuần này
- [x] Đồng bộ phiên bản production lên nhánh `main`.
- [x] Rà soát cấu hình môi trường sau các lần hợp nhất.
- [ ] Hoàn thiện toàn bộ deliverables còn thiếu.

### Đã hoàn thành
- Đồng bộ `main` với phiên bản production sau khi xử lý regression từ nhánh AI.
- Cập nhật `.env.example` theo cấu hình hiện tại của hệ thống.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Phiên bản AI mới ghi đè một số thay đổi production. | Đối chiếu các nhánh và đồng bộ lại phiên bản production lên `main`. | Mã nguồn chính trở lại trạng thái tích hợp mới nhất. |

### Bài học
- File cấu hình mẫu phải được cập nhật cùng code và không chứa secret.
- Trước Demo Day cần đóng băng phiên bản và ưu tiên kiểm thử, tài liệu, bằng chứng đánh giá.

### Kế hoạch tuần sau
- [ ] Hoàn thiện `eval/report.md` bằng metrics và kết quả test thực tế.
- [ ] Cập nhật `WORKLOG.md` và kiểm tra toàn bộ deliverables.
- [ ] Hoàn thiện pitch deck, video demo và kiểm tra deployment.
