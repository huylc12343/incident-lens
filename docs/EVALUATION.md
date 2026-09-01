# Đánh giá evidence-based

## 1. Phạm vi và nguồn kết quả

P-207 được đánh giá từ evidence có timestamp, không chỉ từ nhãn phân loại cuối. AI nhận video để tạo incident window, timeline và claim; ground truth chỉ được dùng sau inference để chấm kết quả, không được đưa vào prompt phân tích.

Kết quả định lượng hiện có:

- Bộ đánh giá: `golden_set`.
- Số mẫu hoàn thành: **38/38**, không có mẫu lỗi.
- Thời điểm tạo kết quả: **2026-08-29**.
- Dữ liệu chi tiết từng mẫu: `eval/results_1/*.json`.
- Metric tổng hợp: [`eval/results_1/metric.json`](../eval/results_1/metric.json).
- Báo cáo đầy đủ: [`eval/report.md`](../eval/report.md).

Nhãn `provisional_manual_ground_truth` hoặc `needs_human_validation` vẫn được xem là provisional. Không diễn giải nhãn thiếu hoặc chưa xác nhận thành kết quả pass/fail tuyệt đối.

## 2. Quy tắc đánh giá evidence

Khi có telemetry, backend chỉ cung cấp cho verifier các evidence ID hợp lệ trong incident window và gần timestamp của claim.

| Trạng thái | Ý nghĩa |
|---|---|
| `supported` | Có evidence telemetry hợp lệ và trực tiếp hỗ trợ claim. |
| `contradicted` | Có evidence telemetry hợp lệ và trực tiếp mâu thuẫn claim; có thể kích hoạt một focused re-analysis. |
| `unverified` | Thiếu tín hiệu, evidence nằm ngoài dung sai timestamp hoặc không đủ căn cứ. Trạng thái này không đồng nghĩa với claim sai. |

Các trường được đối chiếu gồm quyết định có incident, loại sự cố, `t0`, incident window, timeline, claim và evidence ID.

## 3. Kết quả benchmark 38 mẫu

### 3.1 Tổng quan

| Metric | Target | Actual | Kết quả |
|---|---:|---:|---|
| Accident-type accuracy | >80% | **86.84%** | ✅ Đạt |
| Average wall time | <3 giây/mẫu | **64.77 giây/mẫu** | ❌ Chưa đạt |
| User satisfaction | >4/5 | **4.0/5** từ 6 người | ❌ Bằng 4, chưa vượt target |
| Test coverage | >60% | Chưa đo được do lỗi collection OpenCV | ⚠️ Chưa có số liệu |

### 3.2 Incident detection

| Stage | Precision | Recall | F1 | TP | FP | FN | TN |
|---|---:|---:|---:|---:|---:|---:|---:|
| VLM | 1.0000 | 0.5769 | 0.7317 | 15 | 0 | 11 | 12 |
| Verifier/report | 1.0000 | 0.9615 | 0.9804 | 25 | 0 | 1 | 12 |

Trên 26 mẫu có incident, VLM ban đầu nhận đúng 15 mẫu. Sau verification/report, hệ thống nhận đúng 25 mẫu và không tạo false positive trong bộ 38 mẫu. Đây là kết quả pipeline tổng thể, không nên diễn giải rằng verifier độc lập luôn có thể sửa mọi false negative trên dữ liệu khác.

### 3.3 Phân loại loại sự cố

| Metric | Giá trị |
|---|---:|
| Accuracy | 0.8684 |
| Precision | 0.7624 |
| Recall | 0.7024 |
| F1 | 0.7227 |

Phân bố ground truth:

| Nhãn | Số mẫu |
|---|---:|
| `no_incident` | 12 |
| `crossing_collision` | 10 |
| `vehicle_collision` | 7 |
| `environment_collision` | 5 |
| `pedestrian_collision` | 4 |
| **Tổng** | **38** |

### 3.4 Temporal localisation

| Stage | Median `t0` error | Temporal IoU mean | Temporal IoU median | Số mẫu định vị được |
|---|---:|---:|---:|---:|
| VLM | 0.20 giây | 0.3821 | 0.3960 | 15 |
| Report | 0.25 giây | 0.4053 | 0.4000 | 25 |

Trong so sánh paired trên cùng 15 mẫu, Temporal IoU mean của VLM và report đều là **0.3821**, delta bằng **0.0**. Mức tăng mean toàn bộ của report chủ yếu đến từ việc report định vị được nhiều incident hơn, không phải do cải thiện overlap trên 15 mẫu paired.

### 3.5 Evidence và chất lượng báo cáo

| Metric | Giá trị |
|---|---:|
| Evidence ID precision | 1.0000 |
| Claim-evidence validity rate | 1.0000 |
| Report decision consistency | 1.0000 |
| Báo cáo qua consistency check | 38/38 |
| Claim `supported` | 74.38% |
| Claim `contradicted` | 0.00% |
| Claim `unverified` | 25.62% |

Tổng cộng có **121 verification results**. Precision evidence bằng 1.0 chỉ xác nhận các ID được tham chiếu đều hợp lệ theo tập evidence backend cho phép; metric này không chứng minh evidence đã bao phủ mọi sự kiện trong video.

### 3.6 Chi phí và thời gian xử lý

| Metric | Giá trị |
|---|---:|
| Chi phí trung bình/mẫu | $0.004316 |
| Tổng chi phí 38 mẫu | $0.164010 |
| Input tokens trung bình/mẫu | 28,938.42 |
| Output tokens trung bình/mẫu | 3,778.08 |
| Tổng tokens trung bình/mẫu | 32,716.50 |
| Số lượt gọi model trung bình/mẫu | 3.63 |
| Wall time trung bình/mẫu | 64.77 giây |
| Model time trung bình/mẫu | 61.97 giây |

## 4. Trạng thái kiểm thử code

Lệnh chuẩn:

```bash
python -m pytest tests/ -v
```

Kết quả gần nhất ngày **2026-09-01**:

| Nhóm | Passed | Failed/Error | Trạng thái |
|---|---:|---:|---|
| Agent và routing | 55 | 2 E2E failures | ⚠️ Bị ảnh hưởng bởi OpenCV |
| API incident | 17 | 0 | ✅ Pass |
| Verification và reporting | 54 | 0 | ✅ Pass |
| Upload, media và video memory | 41 | 0 | ✅ Pass |
| Prompt và auto-reanalysis | 25 | 0 | ✅ Pass |
| Metrics đánh giá | 21 | 0 | ✅ Pass |
| LangSmith tracing | 11 | 0 | ✅ Pass |
| Video/CV pipeline | 0 | 1 collection error | ❌ Bị chặn bởi OpenCV |

Sáu nhóm hoàn chỉnh có tổng cộng **169 test pass**. Nhóm Agent/Routing có thêm **55 test pass** trước hai lỗi E2E. Suite chưa thể thu coverage đầy đủ vì `tests/test_cv_pipeline.py` lỗi collection khi import `cv2`:

```text
ImportError: ERROR: recursion is detected during loading of "cv2"
binary extensions. Check OpenCV installation.
```

Môi trường tại thời điểm chạy có đồng thời `opencv-python 4.12.0.88` và `opencv-contrib-python 4.11.0.86`, trong khi `requirements.txt` chỉ yêu cầu `opencv-python`. Kết quả benchmark 38 mẫu ở phần 3 vẫn là artifact đã tạo thành công và độc lập với trạng thái collection của lần chạy pytest này.

## 5. CV và privacy benchmark

Repository đã có [`eval/cv_benchmark/annotations.json`](../eval/cv_benchmark/annotations.json), gồm một tập frame được gán nhãn thủ công tối thiểu từ hai video. Tập này phù hợp cho regression và so sánh trước/sau, nhưng chưa đủ để tuyên bố mức privacy production:

- Annotation hiện có các vùng biển số; video nguồn không có khuôn mặt đủ rõ nên face recall là `N/A`.
- Chưa có artifact kết quả chạy detector hoặc báo cáo recall tổng hợp được commit cùng annotation.
- Cần mở rộng lên ít nhất 100–200 frame được gán nhãn độc lập, bao gồm nhiều góc nhìn, che khuất, ban đêm, mưa và khuôn mặt nhìn thấy rõ trước khi kết luận deployment-level recall.

## 6. User feedback

Điểm trung bình: **4.0/5** từ **6 người dùng thử**.

| Người feedback | Nhóm/vai trò | Nội dung rút gọn | Rating |
|---|---|---|---:|
| Hồ Xuân Phú | Cohort I | Nên hiển thị confidence, accuracy và latency. | 4/5 |
| Trần Đoàn Quang Vũ | G10-T008 | UI/UX dễ thao tác; nên hỗ trợ upload nhiều phiên video. | 4/5 |
| Bùi Đức Lân | T138 | UI đẹp và chức năng xử lý video phù hợp với một MVP. | 5/5 |
| Vũ Hải Nam | T102 | Xử lý còn lâu; nên hiển thị thời gian chờ ước lượng. | 3/5 |
| Nguyễn Thanh Tùng | T202 | UI/UX rõ ràng; nên hỗ trợ upload nhiều phiên video. | 4/5 |
| Lab Coach Mê Linh | Lab Coach | Cần làm rõ timeline–evidence, metric overlap và Top-K; ưu tiên recall để hạn chế bỏ sót lỗi. | 4/5 |

## 7. Demo và giới hạn hiện tại

- Demo Day chưa diễn ra; người tham gia dự kiến là toàn bộ 4 thành viên team T207-Cá Hồi.
- VLM ban đầu bỏ sót 11/26 incident; recall phân loại loại sự cố là 70.24%.
- Thời gian xử lý trung bình 64.77 giây/mẫu, chưa đạt target dưới 3 giây.
- 25.62% claim ở trạng thái `unverified`, cần thêm evidence hoặc human review.
- Annotation `INC_LOSS_CONTROL_001` có mâu thuẫn giữa `t_start=20.0` và `t0=2.75`; không dùng mẫu này cho kết luận định lượng cho tới khi nhãn được sửa hoặc version hóa.
- Chưa có coverage tổng vì pytest bị lỗi collection OpenCV; trạng thái này được ghi nhận, không được đổi thành pass.

## 8. Việc cần làm tiếp

- Giảm false negative và cải thiện recall phân loại sự cố.
- Công khai cách tính timeline–evidence, Temporal IoU và cấu hình Top-K trên UI hoặc tài liệu.
- Tối ưu số lượt gọi model và latency xử lý.
- Rà soát claim `unverified` và bổ sung evidence phù hợp.
- Sửa hoặc version hóa annotation `INC_LOSS_CONTROL_001`.
- Mở rộng và chạy CV/privacy benchmark để có recall thực tế.
- Sau Demo Day, bổ sung ngày demo, feedback và issue phát hiện.
