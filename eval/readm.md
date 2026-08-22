# Evaluation

Evaluator chạy trực tiếp production graph trong `src`, không gọi API port 8000 và không sửa `.env`. Nó giữ nguyên auto re-analysis, dùng dữ liệu trong `golden_set/`, rồi ghi kết quả vào `eval/results/latest.json`.

Yêu cầu: `.env` đã có `DASHSCOPE_API_KEY` và `OPENAI_API_KEY` hợp lệ.

Chạy toàn bộ golden set:

```bash
.venv/bin/python -m eval.run --analysis-prompt "Phân tích sự cố giao thông trong toàn bộ video."
```

Kết quả gồm metric VLM, verifier và report. `type_of_accident_f1` hiện để `null` vì golden label `cut_in_collision` chưa có mapping sang enum report.
