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
