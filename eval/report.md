# Evaluation Report

> Báo cáo đánh giá chất lượng sản phẩm của team T207-Cá Hồi theo tiêu chí BTC.

---

## 1. Evaluation Scope

- Bộ đánh giá: `golden_set`
- Tổng số mẫu: **38**
- Số mẫu hoàn thành: **38/38**
- Mẫu lỗi khi chạy benchmark: **0**
- Thời điểm tạo kết quả: **2026-08-29**
- Nguồn dữ liệu định lượng: `eval/results_1/metric.json`
- Nguồn trình bày: [T207_slide_MVP — trang 14–20](https://docs.google.com/presentation/d/1iE9XS6sWDYN4fX0u7A0LU-ADVvzPgMgRplMgxMQ5gBw/edit?slide=id.g3f8a504207d_4_0)

## 2. Summary Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Accident-type accuracy | >80% | **86.84%** | ✅ Đạt |
| Average wall time | <3s | **64.77s/mẫu** | ❌ Chưa đạt |
| User satisfaction | >4/5 | **4.0/5** (6 người) | ❌ Chưa vượt target |
| Test coverage | >60% | Chưa đo được do lỗi collection | ⚠️ Bị chặn |

### 2.1 Incident Detection

| Stage | Precision | Recall | F1 | TP | FP | FN | TN |
|-------|----------:|-------:|---:|---:|---:|---:|---:|
| VLM | 1.0000 | 0.5769 | 0.7317 | 15 | 0 | 11 | 12 |
| Verifier | 1.0000 | 0.9615 | 0.9804 | 25 | 0 | 1 | 12 |

Verifier nâng recall từ **57.69%** lên **96.15%** và F1 từ **73.17%** lên **98.04%**, đồng thời không tạo false positive trong bộ 38 mẫu.

### 2.2 Accident-Type Classification

| Metric | Value |
|--------|------:|
| Accuracy | 0.8684 |
| Precision | 0.7624 |
| Recall | 0.7024 |
| F1 | 0.7227 |

Kết quả được tính trên **38 mẫu**.

### 2.3 Temporal Localisation

| Stage | Median t0 error | Temporal IoU mean | Temporal IoU median | Số mẫu định vị được |
|-------|----------------:|------------------:|--------------------:|---------------------:|
| VLM | 0.20s | 0.3821 | 0.3960 | 15 |
| Report | 0.25s | 0.4053 | 0.4000 | 25 |

Trong so sánh paired trên 15 mẫu, Temporal IoU mean của VLM và report đều là **0.3821**, delta bằng **0.0**.

### 2.4 Evidence and Report Quality

| Metric | Value |
|--------|------:|
| Evidence ID precision | 1.0000 |
| Claim-evidence validity rate | 1.0000 |
| Report decision consistency | 1.0000 |
| Report consistency passed | 38/38 |
| Supported claims | 74.38% |
| Contradicted claims | 0.00% |
| Unverified claims | 25.62% |

Tổng cộng có **121 verification results**.

### 2.5 Cost, Tokens and Runtime

| Metric | Actual |
|--------|-------:|
| Chi phí trung bình/mẫu | $0.004316 |
| Tổng chi phí 38 mẫu | $0.164010 |
| Input tokens trung bình/mẫu | 28,938.42 |
| Output tokens trung bình/mẫu | 3,778.08 |
| Tổng tokens trung bình/mẫu | 32,716.50 |
| Số lượt gọi model trung bình/mẫu | 3.63 |
| Wall time trung bình/mẫu | 64.77s |
| Model time trung bình/mẫu | 61.97s |

### 2.6 Ground-Truth Distribution

| Nhãn | Số mẫu |
|------|-------:|
| `no_incident` | 12 |
| `crossing_collision` | 10 |
| `vehicle_collision` | 7 |
| `environment_collision` | 5 |
| `pedestrian_collision` | 4 |
| **Tổng** | **38** |

## 3. Test Results

### Unit and Integration Tests

Lệnh chạy toàn bộ suite:

```bash
python -m pytest tests/ -v
```

Runner theo từng nhóm chức năng:

```bash
python tests/run_suite.py --group all
python tests/run_suite.py --group agent-routing
```

Kết quả ngày **2026-09-01**:

| Nhóm kiểm thử | Passed | Failed/Error | Trạng thái |
|---------------|-------:|-------------:|------------|
| Agent và routing | 55 | 2 E2E failures | ⚠️ Bị ảnh hưởng bởi OpenCV |
| API incident | 17 | 0 | ✅ Pass |
| Verification và reporting | 54 | 0 | ✅ Pass |
| Upload, media và video memory | 41 | 0 | ✅ Pass |
| Prompt và auto-reanalysis | 25 | 0 | ✅ Pass |
| Metrics đánh giá | 21 | 0 | ✅ Pass |
| LangSmith tracing | 11 | 0 | ✅ Pass |
| Video/CV pipeline | 0 | 1 collection error | ❌ Bị chặn bởi OpenCV |

| Hạng mục | Kết quả |
|----------|---------|
| Test pass trong 6 nhóm hoàn chỉnh | 169 |
| Agent/routing pass trước hai E2E failures | 55 |
| Collection errors | 1 ở nhóm Video/CV |
| Trạng thái tổng | ⚠️ 6/8 nhóm pass hoàn chỉnh |

Pytest dừng khi import `tests/test_cv_pipeline.py`:

```text
ImportError: ERROR: recursion is detected during loading of "cv2"
binary extensions. Check OpenCV installation.
```

Hai E2E failures của Agent/Routing cũng đi qua pipeline media nên kết thúc ở trạng thái `failed` khi `cv2` không import được. Máy hiện cài đồng thời `opencv-python 4.12.0.88` và `opencv-contrib-python 4.11.0.86`, trong khi `requirements.txt` chỉ yêu cầu `opencv-python`. Cần làm sạch môi trường OpenCV rồi chạy lại hai nhóm bị chặn và toàn bộ suite. Chưa thể kết luận test coverage trước khi collection hoàn tất.

### Integration Scenarios

| Luồng | Bằng chứng hiện có | Trạng thái |
|------|--------------------|-----------|
| Upload → incident processing → polling | Có test API, async worker và workflow trong `tests/` | ⚠️ Chưa chạy hết suite |
| Video analysis → verification → report | Có test agent, prompts, verification và reporting | ⚠️ Chưa chạy hết suite |
| Human review → edit → reanalysis | Có test review node, review edits và auto-reanalysis | ⚠️ Chưa chạy hết suite |
| Ground truth → evaluation metrics | Có `eval/results_1/metric.json` từ 38 mẫu | ✅ Có kết quả benchmark |

## 4. User Feedback

Điểm hài lòng trung bình: **4.0/5**, tính từ **6 người dùng thử**.

| User | Vai trò/nhóm | Feedback | Rating |
|------|--------------|----------|--------|
| Hồ Xuân Phú | Học viên Cohort I | Giao diện người dùng nên hiển thị thêm độ tin cậy, độ chính xác và latency của kết quả. | 4/5 |
| Trần Đoàn Quang Vũ | Thành viên G10-T008 | UI đơn giản, dễ nhìn, giúp kỹ sư dễ dàng thao tác và làm việc. UX hướng dẫn rõ những bước kỹ sư cần thực hiện. Đề xuất hỗ trợ upload nhiều phiên video cùng lúc. | 4/5 |
| Bùi Đức Lân | Thành viên T138 | Sản phẩm được hoàn thiện tốt và UI đẹp. Người dùng chưa có video camera xe máy thực tế nhưng đã thử bằng video trên mạng và đánh giá khả năng xử lý ở mức tốt đối với một sản phẩm MVP. | 5/5 |
| Vũ Hải Nam | Thành viên T102 | Thời gian xử lý video còn lâu; đề xuất bổ sung thời gian xử lý ước lượng để người dùng biết cần chờ bao lâu. | 3/5 |
| Nguyễn Thanh Tùng | Thành viên T202 | UI đơn giản, dễ nhìn, giúp kỹ sư dễ dàng thao tác và làm việc. UX hướng dẫn rõ những bước kỹ sư cần thực hiện. Đề xuất hỗ trợ upload nhiều phiên video cùng lúc. | 4/5 |
| Lab Coach Mê Linh | Lab Coach | Bài toán hay, giao diện đơn giản và dễ dùng. Cần trình bày rõ cách liên kết timeline với evidence, metric đo độ trùng khớp và giá trị Top-K. Hệ thống nên ưu tiên recall để bắt đủ lỗi vì mỗi trường hợp bị bỏ sót có thể là một bug quan trọng. | 4/5 |

## 5. Demo Results

- Trạng thái: **Demo chưa diễn ra**
- Ngày demo: **Chưa đến lịch**
- Người tham gia dự kiến: **Toàn bộ team T207-Cá Hồi (4 thành viên)**
- Feedback chung: **Chưa có vì demo chưa diễn ra**
- Issues phát hiện: **Chưa có vì demo chưa diễn ra**

## 6. Limitations

- VLM gốc bỏ sót 11/26 incident; verifier giảm false negative xuống còn 1/26.
- Recall phân loại loại tai nạn mới đạt 70.24%, thấp hơn accuracy tổng thể.
- Thời gian xử lý trung bình 64.77 giây/mẫu, chưa đạt target dưới 3 giây.
- 25.62% claim ở trạng thái `unverified`, cần thêm evidence hoặc human review.
- Bộ test chưa chạy hoàn chỉnh do lỗi cài đặt OpenCV.
- Annotation của `INC_LOSS_CONTROL_001` có mâu thuẫn giữa `t_start=20.0` và `t0=2.75`; không nên dùng mẫu này cho kết luận định lượng cho đến khi nhãn được sửa hoặc version hóa.

## 7. Action Items

- [ ] Sửa môi trường OpenCV và chạy lại `python -m pytest tests/ -v`.
- [ ] Chạy coverage và cập nhật tỷ lệ thực tế vào báo cáo.
- [ ] Giảm false negative của VLM và cải thiện recall phân loại tai nạn.
- [ ] Công khai cách tính timeline–evidence, Temporal IoU và cấu hình Top-K trên giao diện hoặc tài liệu.
- [ ] Tối ưu số lượt gọi model và thời gian xử lý trung bình.
- [ ] Rà soát các claim `unverified` và bổ sung evidence phù hợp.
- [ ] Sửa hoặc version hóa annotation `INC_LOSS_CONTROL_001`.
- [ ] Thu thập feedback có rating từ người dùng thử.
- [ ] Sau khi demo diễn ra, bổ sung ngày thực tế, feedback và issue phát hiện.
