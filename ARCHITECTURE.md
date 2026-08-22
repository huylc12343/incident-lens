# Kiến trúc P-207 / Incident Analysis Agent

P-207 là MVP hỗ trợ kỹ sư rà soát sự cố giao thông từ video camera trước và log telemetry CSV tùy chọn. AI tạo timeline và claim có bằng chứng; quyết định cuối cùng thuộc về người review.

## Thành phần

| Lớp | Thành phần thực tế | Trách nhiệm |
| --- | --- | --- |
| Web UI | Next.js 15, React 19, TypeScript (`frontend/`) | Upload, theo dõi xử lý, xem clip/timeline/evidence/telemetry, gửi quyết định review. |
| API | FastAPI (`src/main.py`, `src/api/`) | Upload video/log, tạo/lấy incident, nhận review; có `/live` và `/ready`. |
| Điều phối | LangGraph (`src/agents/incident_graph.py`) | Lưu state/checkpoint, điều phối các node phân tích, re-analysis và human review. |
| AI & media | `src/services/` | Chuẩn hóa/cắt video, trích frame, gọi VLM, phân tích log, verification, tạo report và artifacts. |
| Lưu trữ | SQLite | LangGraph checkpointer cho incident đang review và report repository cho incident terminal. |

## Luồng xử lý

```text
video + CSV telemetry (tùy chọn)
  → validate/upload qua FastAPI
  → normalize video; có thể blur mặt và biển số
  → VLM: Qwen native video hoặc contract timestamped frames
  → VideoMemory: incident window, timeline, claims và evidence theo claim
  → canonicalize evidence và cắt incident clip
  → nếu có CSV: phân tích telemetry, events/metrics/charts
  → verification claim với log: supported | contradicted | unverified
  → một focused re-analysis tự động khi có contradicted (nếu bật)
  → DraftReport 10 phần
  → LangGraph interrupt chờ human review
  → approve | edit | reanalyze | not_incident
  → checkpoint hoặc report terminal SQLite
```

VLM Qwen/DashScope nhận video native đã chuẩn hóa. Contract timestamped frames vẫn được giữ trong model/workflow cho luồng frame và dữ liệu đã lưu. OpenAI được dùng cho verification có structured output và cho narrative report; các provider/model phụ thuộc cấu hình môi trường.

## Evidence và verification

`VideoMemory` lưu claim với `timestamp_s`, danh sách `evidence` và `verification_status`. Backend canonicalize evidence về frame nguồn hợp lệ; VLM không được tự đưa claim vào trạng thái đã xác minh.

Với incident có log, verification chỉ dùng mẫu telemetry trong incident window và dung sai timestamp cấu hình. Mỗi kết quả có một trong ba trạng thái:

- `supported`: log có bằng chứng trực tiếp hỗ trợ claim.
- `contradicted`: log có bằng chứng trực tiếp mâu thuẫn claim.
- `unverified`: thiếu tín hiệu, ngoài dung sai thời gian, hoặc không có evidence log hợp lệ; đây không phải kết luận phủ định claim.

Claim `contradicted` có thể kích hoạt một lần re-analysis tập trung rồi verification lại. Nếu không có log, claim giữ `unverified` thay vì được gắn là verified.

## Human in the loop

Node `review` gọi LangGraph `interrupt` với report, artifacts, claims, cảnh báo và bốn action được allowlist. `approve` và `not_incident` là terminal. `edit` chỉ cập nhật các narrative field được cho phép và quay lại review; `reanalyze` yêu cầu feedback cùng target claim IDs rồi chạy lại phần liên quan. Vì vậy UI/API không tự đưa ra quyết định thay kỹ sư.

## Quyền riêng tư và CV

Trước native-video analysis, cấu hình `VIDEO_REDACTION_ENABLED` có thể bật pipeline trong `src/services/detect_and_blur.py`: YOLO phát hiện biển số và khuôn mặt trên từng frame, tracker chỉ bắc cầu cho miss ngắn, sau đó Gaussian blur ROI đã được padding. Đây là biện pháp giảm lộ dữ liệu, không phải bảo đảm ẩn danh tuyệt đối. Xem [Privacy](docs/PRIVACY.md) để biết giới hạn và tình trạng benchmark.

## Ranh giới MVP

MVP có API, workflow, review, artifacts và persistence đơn tiến trình. Repository hiện không chứng minh authentication/authorization production, object storage bên ngoài, queue phân tán hay multi-worker SQLite. Việc gọi model thật phụ thuộc API key/cost và không được suy ra chỉ từ unit test mock provider.
