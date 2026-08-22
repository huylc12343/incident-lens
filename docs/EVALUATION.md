# Đánh giá evidence-based

## Phạm vi và nguyên tắc

Đánh giá của P-207 bắt đầu từ evidence có timestamp, không chỉ từ nhãn phân loại cuối. AI nhận video để sinh incident window, timeline và claim; ground truth/annotation không được gửi vào prompt phân tích. Khi có telemetry, backend lấy mẫu gần claim trong incident window và chỉ cho verification dùng `allowed_evidence_ids` do backend tạo.

Ground truth là dữ liệu đối chiếu thủ công/dataset, không phải nguồn để model suy luận. Nhãn `provisional_manual_ground_truth` hoặc `needs_human_validation` phải được ghi nhận là provisional, không được coi là sự thật tuyệt đối.

## Cách chấm một claim

| Trạng thái | Ý nghĩa đánh giá |
| --- | --- |
| `supported` | Có evidence log hợp lệ, gần timestamp và trực tiếp hỗ trợ claim. |
| `contradicted` | Có evidence log hợp lệ trực tiếp mâu thuẫn claim; có thể trigger một focused re-analysis. |
| `unverified` | Không đủ tín hiệu/evidence log, hoặc ngoài dung sai timestamp. Không được chấm là `contradicted` chỉ vì dữ liệu thiếu. |

Người đánh giá so sánh loại sự cố, cửa sổ thời gian, `t0`, claim/timeline và evidence ID. Cần ghi rõ dữ liệu nào là video, telemetry hay annotation; không đổi một nhãn thiếu dữ liệu thành fail/pass.

## Bộ ca thủ công

Checkout đang có hai bộ mock có ground truth/annotation (`data_mock/INC_LOSS_CONTROL_001` và `data_mock/data1`) và một bộ mock frontend. Không có bộ artifact đã chạy gồm năm TC dưới `eval/`; vì vậy bảng này là **protocol kiểm thử thủ công cần chạy**, không phải kết quả thực nghiệm đã xác nhận.

| TC | Dữ liệu/kịch bản | Kiểm tra mong muốn | Trạng thái bằng chứng hiện có |
| --- | --- | --- | --- |
| TC1 | `INC_LOSS_CONTROL_001` video + telemetry | Timeline, brake/deceleration và evidence có timestamp được trình bày để review. | Có annotation nhưng `t_start=20` lớn hơn `t0=2.75`; không dùng để tính metric tổng hợp trước khi sửa nhãn. |
| TC2 | `data_mock/data1` — xe rời cầu/rơi xuống nước | So sánh prediction VLM với ground truth thủ công/provisional, sau đó reviewer xác nhận hay bác bỏ. | **False-negative của VLM khi prediction không nhận ra sự cố trong khi annotation mô tả road departure/fall.** Nhãn còn provisional và cần human validation; phải giữ false-negative này trong báo cáo, không diễn giải thành pass. |
| TC3 | `data_mock/data1` + CSV telemetry | Claim có timestamp gần log được verification; signal thiếu/xa timestamp phải là `unverified`. | Có dữ liệu mock; chưa có run artifact được lưu trong `eval/`. |
| TC4 | Same video, không gửi CSV | Claim video-only không được tự gắn `supported`; report nêu không có log. | Được bảo vệ bởi contract/test; chưa có kết quả manual run lưu trong `eval/`. |
| TC5 | Một claim contradicted từ telemetry | Kiểm tra focused re-analysis tối đa một lần, re-verify và không sửa claim ngoài target. | Có unit/integration test workflow; chưa có artifact manual benchmark. |

TC2 được ghi là false-negative theo yêu cầu đối chiếu hiện có; điều đó không biến annotation provisional thành nhãn tuyệt đối. Cần lưu prediction, timestamp và review outcome của lần chạy thực để kết luận định lượng.

## Kết quả đã chạy và phần chưa chạy

- **Đã có trong repository:** unit/integration tests cho video memory, verification, workflow, API và prompts; mock data/annotation nêu trên.
- **Không có trong checkout tại thời điểm tài liệu này được viết:** kết quả chạy 5 TC, confusion matrix, latency benchmark, hoặc report CV benchmark có thể tái lập. `eval/results/report.md` chỉ là template chưa điền số liệu.
- **Kế hoạch:** chạy từng TC với cùng version model/config, lưu request metadata không nhạy cảm, prediction, evidence IDs, review verdict và lý do mismatch; chỉ sau đó mới tính accuracy/t0 delta/timeline overlap.

## Cảnh báo dữ liệu

`INC_LOSS_CONTROL_001` có timeline ground truth nội bộ mâu thuẫn (`t_start=20.0`, `t0=2.75`). Không dùng nó làm mẫu tính accuracy cho đến khi annotation được sửa hoặc version hóa lại. Điều này là hạn chế của dữ liệu đánh giá, không nên che giấu trong PR/demo.
