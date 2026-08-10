# Incident Analysis Agent

Backend FastAPI + LangGraph phân tích video giao thông dưới 60 giây, kết hợp log xe tùy chọn, tạo báo cáo 10 mục và dừng tại bước kỹ thuật viên review. Dự án có Streamlit client độc lập trong `main_test.py` để chạy toàn bộ lifecycle qua HTTP API.

## Luồng xử lý

```text
video + optional log
  → VLM tìm t_start, t0, t_end, timeline và claims
  → cắt incident clip + representative frames
  → nếu có log: cắt log + metrics/events + 4 charts + verify claims
  → nếu có conflict: focused VLM re-analysis tối đa 1 lần + verify lại
  → backend lắp báo cáo cố định 10 mục
  → LangGraph interrupt chờ human review
  → approve | edit | reanalyze | not_incident
  → SQLite checkpoint + terminal report repository
```

`edit` chỉ sửa sáu trường narrative và quay lại `awaiting_review`; không tự approve và không gọi LLM. `reanalyze` bắt buộc có feedback cùng target claim IDs, sau đó tạo lại báo cáo và quay lại review. Chỉ `approve` và `not_incident` là terminal.

## Cài đặt

Yêu cầu Python 3.11 và FFmpeg. `MediaService` ưu tiên `ffmpeg`/`ffprobe` trong `PATH`; package `imageio-ffmpeg` cung cấp fallback cho FFmpeg.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Cấu hình tối thiểu cho OpenAI timestamped frames:

```dotenv
OPENAI_API_KEY=...
VLM_PROVIDER=openai
VLM_INPUT_MODE=timestamped_frames
INCIDENT_INPUT_ROOTS=./data_mock
INCIDENT_UPLOAD_DIR=./data/uploads
ARTIFACT_DIR=./data/artifacts
INCIDENT_DATABASE_PATH=./data/incident_reports.sqlite3
INCIDENT_CHECKPOINT_PATH=./data/incident_checkpoints.sqlite3
```

Incident clip mặc định có tối thiểu 5 giây, thêm 1 giây trước và 2 giây sau window do VLM xác định. Có thể điều chỉnh bằng `INCIDENT_CLIP_MIN_DURATION_S`, `INCIDENT_CLIP_PRE_ROLL_S` và `INCIDENT_CLIP_POST_ROLL_S`. Ảnh `representative_frame` được chọn gần `t0` thay vì lấy frame đầu tiên.

Qwen native video dùng `VLM_PROVIDER=qwen`, `VLM_INPUT_MODE=native_video` và `DASHSCOPE_API_KEY`. Video local nhỏ hơn `QWEN_BASE64_MAX_VIDEO_BYTES` (mặc định 7 MB) được gửi bằng Base64 Data URL. Video lớn hơn ngưỡng cần `QWEN_ARTIFACT_URL_BASE` công khai `ARTIFACT_DIR`. Qwen gọi `qwen3-vl-flash` qua DashScope chat completions. Gemini được giữ lại chỉ để tương thích cấu hình cũ.

Streamlit upload file vào `INCIDENT_UPLOAD_DIR`; backend kiểm tra phần mở rộng, dung lượng, path root, file tồn tại và video không quá 60 giây. URL từ xa và external object storage không thuộc baseline.

## Chạy backend và Streamlit

Terminal 1:

```bash
uvicorn src.main:app --reload --port 8000
```

Terminal 2:

```bash
streamlit run main_test.py
```

Swagger: `http://localhost:8000/docs`.

Trong Streamlit, chọn video bằng nút **Browse files** và chọn log CSV nếu có; không cần nhập đường dẫn file.

Workflow chạy đồng bộ đến Human Review nên VLM + verification + report có thể mất vài phút. Streamlit chờ tối đa 900 giây và hiển thị riêng lỗi kết nối, timeout hoặc response backend không phải JSON; xem terminal Uvicorn nếu backend báo HTTP 500.

Nếu OpenAI verification thất bại, workflow không còn kết thúc bằng lỗi: snapshot ghi warning và backend tạo báo cáo fallback từ `video_summary`, timeline và evidence trong claims mà VLM đã trả. Khi verification của incident có log không khả dụng, lần gọi report model được bỏ qua. Sau khi sửa `.env` hoặc cập nhật code, phải khởi động lại FastAPI và dùng incident ID mới vì incident cũ vẫn có checkpoint.

## Incident API

### Upload video và log

```http
POST /api/v1/incidents/uploads
Content-Type: multipart/form-data

video=<video file, bắt buộc>
log=<CSV file, tùy chọn>
```

Video hỗ trợ `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`; log hỗ trợ `.csv`. Response trả `video_uri` và `log_uri` nội bộ để dùng trong request tạo incident.

### Tạo incident

```http
POST /api/v1/incidents
Content-Type: application/json

{
  "incident_id": "INC-001",
  "video_uri": "data_mock/front_camera.mp4",
  "log_uri": "data_mock/vehicle_state.csv",
  "analysis_prompt": "Phân tích sự cố trong video."
}
```

### Lấy snapshot

```http
GET /api/v1/incidents/INC-001
```

Snapshot chỉ trả public lifecycle, báo cáo, claims, artifacts, warnings và audit; không trả raw graph state, API key, prompt nội bộ, remote provider handle hay chain-of-thought.

### Gửi review

```http
POST /api/v1/incidents/INC-001/review
Content-Type: application/json

{
  "action": "approve",
  "reviewer": "reviewer@example.com"
}
```

Các payload khác:

```json
{"action":"edit","reviewer":"tech","edits":{"summary":"Nội dung đã sửa"}}
{"action":"reanalyze","reviewer":"tech","feedback":"Kiểm tra lại phanh","target_claim_ids":["claim-1"]}
{"action":"not_incident","reviewer":"tech","reason":"Không phải sự cố an toàn"}
```

Create/review trả `202` khi đang chờ review, `200` khi terminal; `404` cho incident không tồn tại, `409` cho duplicate/sai lifecycle và `422` cho schema/input không hợp lệ.

## Báo cáo 10 mục

`DraftReport` gồm đúng 10 section:

1. Thông tin chung.
2. Khoảng thời gian sự cố.
3. Tóm tắt sự cố.
4. Timeline và typed events.
5. Quan sát video và typed observations.
6. Kết quả log và typed metrics/events.
7. Đối chiếu và typed claim verification.
8. Nguyên nhân giả thuyết.
9. Evidence/artifact/warnings.
10. Review status.

LLM chỉ sinh sáu narrative fields. Backend sở hữu timestamps, metrics, kết quả verification, evidence/artifact URI, warning và review status. Video-only luôn ghi `Không có dữ liệu log.`.

## Persistence

- `INCIDENT_CHECKPOINT_PATH`: SQLite LangGraph checkpoint để GET/resume incident `awaiting_review` sau process restart.
- `INCIDENT_DATABASE_PATH`: SQLite repository cho terminal `approved | not_incident`.
- Qwen không tạo remote handle; DashScope đọc native video từ URL công khai của artifact.

## Kiểm thử

```bash
ruff check src tests main_test.py
ruff format --check src tests main_test.py
python -m compileall -q src tests main_test.py
pytest tests -v --tb=short
pip check
```

E2E tests chạy graph, API, SQLite restart, FFmpeg, log và chart thật với asset trong `data_mock/`; provider SDK chỉ được mock tại SDK boundary nên không phát sinh chi phí model.

## Giới hạn hiện tại

- Chưa có authentication/authorization, external object storage, queue phân tán hoặc production observability.
- SQLite phù hợp demo/single-process; deployment nhiều worker cần database/checkpointer có concurrency model phù hợp hơn.
- Live startup FastAPI/Streamlit và E2E mocked-provider đã được kiểm tra. Chưa gọi model thật vì không có explicit approval phát sinh chi phí, vì vậy kết quả không được tuyên bố production-ready.
