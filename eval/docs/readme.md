# Evaluation

Evaluator chạy trực tiếp production graph trong `src`, không gọi API port 8000 và không sửa `.env`. Nó giữ nguyên auto re-analysis và dùng dữ liệu trong `golden_set/`.

Yêu cầu: `.env` đã có `DASHSCOPE_API_KEY` và `OPENAI_API_KEY` hợp lệ.

Chạy toàn bộ golden set:

```bash
.venv/bin/python -m eval.run --analysis-prompt "Phân tích sự cố giao thông trong toàn bộ video."
```

Mỗi sample được ghi ngay vào `eval/results/<sample_id>.json`. `has_reanalyze=true` nghĩa là graph đã đi vào node auto/manual re-analysis; các field `*_reanalysis_count` chỉ đếm lần re-analysis hoàn tất. Nếu graph hoặc evaluator lỗi, file sample ghi rõ `workflow_error` hoặc `evaluation_error` và `metric.json` liệt kê sample đó trong `failed_samples`.

Khi mạng/API lỗi hoặc cần thay API key, cập nhật `.env` rồi chạy lại cùng lệnh. Chỉ sample chạy thành công mới được bỏ qua; sample workflow lỗi/chưa có file sẽ chạy lại. Dùng `--force` để chạy lại tất cả sample.

`type_of_accident_precision`, `type_of_accident_recall` và `type_of_accident_f1` dùng exact golden label, macro-average trên các lớp xuất hiện trong tập eval.

`metric.json` còn có block `aggregate.resource`: token trung bình (`mean_total_tokens`), thời gian hoàn thành trung bình (`mean_wall_time_s`) và chi phí trung bình (`mean_cost_usd`) mỗi sample, cùng breakdown per-sample ở `metrics.resource`. Chi phí lấy theo bảng giá cố định trong `eval/pricing.py` (sửa cho khớp hợp đồng; model chưa có giá => `cost_usd=null` và nằm trong `unpriced_models`).
