# Báo cáo audit workflow Incident Agent và one-shot API trace

**Ngày audit:** 2026-08-11 (Asia/Bangkok)  
**Nhánh/commit:** `feature/ai-brain` / `66a973c`  
**Phạm vi thay đổi repository:** chỉ thêm báo cáo này và [`api_node_trace_test.py`](../api_node_trace_test.py)  
**Trạng thái kết luận:** workflow chính chạy đến `awaiting_review`, nhưng **chưa đủ điều kiện production** do lỗi bảo mật, evidence provenance và test regression nghiêm trọng.

---

## 1. Tóm tắt điều hành

Một lần gọi model thật đã được thực hiện, đúng theo giới hạn one-shot:

- Chỉ có **1 request mạng** đến DashScope/Qwen, model `qwen3-vl-flash`.
- Guard trong harness chặn request Qwen thứ hai; `VLM_MAX_RETRIES` bị ép về `0` cho run này.
- Verification và report đi qua node/adapter thật nhưng dùng response cục bộ, không gọi OpenAI.
- Workflow thực thi: `validate → analyze_video → cut_incident_video → analyze_log → verify → draft_report → review interrupt`.
- Kết quả cuối: `awaiting_review`; không approve, không ghi terminal report.
- Qwen dùng `14,806` token: `13,634` input, `1,172` output, `0` cached.
- Node local tạo normalized video, incident clip, 48 frame, log slice và 4 chart thành công.

Các phát hiện quan trọng nhất:

| ID | Mức độ | Phát hiện | Tác động |
|---|---|---|---|
| SEC-01 | **Critical** | `.env.example` chứa chuỗi có hình thức credential thật | Có thể bị lạm dụng; phải rotate ngay |
| SEC-02 | **Critical** | Không auth, authorization hoặc rate limit cho upload/create/review/delete/list | Rò dữ liệu, xóa/sửa incident, đốt quota model |
| COR-01 | **High** | Native-video dùng evidence ID do model tự bịa, không ánh xạ tới frame/artifact thật | Báo cáo tạo cảm giác evidence có provenance trong khi không có |
| COR-02 | **High** | VLM được phép tự gắn claim là `supported` trước verification | Video-only có thể công bố claim đã xác minh sai nguồn |
| COR-03 | **High** | Steering threshold `10.0` áp dụng chung cho dữ liệu normalized `[-1,1]` và angle | Bỏ sót sự kiện đánh lái mạnh trong run thật |
| TEST-01 | **High** | Test suite: `41 failed, 124 passed` | Không thể tin cậy regression gate |
| COR-04 | **High** | Qwen gộp/conflate critical proximity với va lan can tại `t0=7.0` | Representative frame không thể hiện sự kiện mà text khẳng định |
| DATA-01 | **High** | Ground truth `INC_LOSS_CONTROL_001` có `t_start=20 > t0=2.75` | Dữ liệu đánh giá tự mâu thuẫn, vi phạm schema workflow |
| COST-01 | Medium | Report model sinh field rồi backend ghi đè 3 field trong case có log | Token/chi phí bị lãng phí |
| REL-01 | Medium | `/health` trả `ok` kể cả workflow startup thất bại | Orchestrator giữ instance không phục vụ được |

---

## 2. Phạm vi, giả định và ranh giới của lần chạy thật

### 2.1 Phạm vi được thực hiện

1. Đọc toàn bộ source trọng yếu của API, graph, node, model, prompt, media, log, verification, report, persistence và UI.
2. Chạy lint, format check, compile và toàn bộ test suite.
3. Chạy một workflow có video + log bằng graph và checkpointer thật.
4. Gửi đúng một normalized video tới DashScope/Qwen.
5. Quan sát input/output từng node từ checkpoint history.
6. Đối chiếu output với annotation, log và representative frames.
7. Tìm lỗi, lỗ hổng, code/biến/state dư và sai lệch tài liệu.

### 2.2 Ranh giới “API thật một lần”

Run không gọi endpoint HTTP `/api/v1/incidents`; nó gọi trực tiếp application service [`incident_workflow_service`](../src/services/incident_runtime.py#L94) để có thể truy xuất checkpoint history chi tiết. “API thật” ở đây là request model bên ngoài tới DashScope.

Chỉ node `analyze_video` dùng provider thật. Hai node sau dùng provider double cục bộ:

- `verify`: adapter [`OpenAIVerificationService`](../src/services/verification.py#L32) chạy thật; `responses.parse` trả một `VerificationResult` cục bộ.
- `draft_report`: adapter [`OpenAIReportService`](../src/services/reporting.py#L23) chạy thật; `responses.parse` trả một `ReportNarrative` cục bộ.

Do đó:

- Kết quả Qwen, media, log, chart, graph routing, checkpoint và report assembly là kết quả runtime thật.
- Chất lượng reasoning của OpenAI verification/report **không được kiểm chứng** trong run này.
- Hai activity “openai / completed / 0 ms / usage null” trong snapshot là local double, không phải request mạng.

### 2.3 Dữ liệu gửi ra ngoài

Sau khi người dùng xác nhận rõ việc egress, normalized video của `data_mock/data1/front_camera.mp4` được gửi dạng Base64 tới:

- Provider: DashScope/Qwen OpenAI-compatible endpoint.
- Model: `qwen3-vl-flash`.
- Kích thước decoded: `930,891` byte.
- SHA-256 normalized video: `f9a6f8f6c99a7dcf4a448f18b4db51f2ca97ff465cd865246674fa79d9001e32`.
- Source video: 17 giây, 1920×1080, 15 FPS, 6,705,579 byte.
- Normalized video: 512×288, 15 FPS, H.264/yuv420p.
- Qwen sampling parameter: `fps=9.0`.

Không gửi `incident.json`, `human_annotation.json`, `agent_output.json`, `metadata.json` hoặc `video_events.csv` tới model. Analysis prompt cũng ghi rõ không dùng ground truth.

---

## 3. Cấu hình runtime đã dùng

| Field | Giá trị |
|---|---|
| `incident_id` | `TRACE-LIVE-ONE-SHOT-20260811` |
| `video_uri` | `data_mock/data1/front_camera.mp4` |
| `log_uri` | `data_mock/data1/vehicle_state.csv` |
| `vlm_provider` | `qwen` |
| `vlm_input_mode` | `native_video` |
| `qwen_vlm_model_name` | `qwen3-vl-flash` |
| `qwen_video_fps` | `9.0` |
| `vlm_video_target` | `512×288 @ 15 FPS` |
| `vlm_max_retries` | `0` trong harness; `.env` bình thường là `2` |
| `auto_reanalysis_enabled` | `false` |
| `log_timestamp_tolerance_s` | `0.5` |
| Runtime artifact root | `/tmp/incident-one-shot-ujs95j3k` |

Input API-level:

```json
{
  "incident_id": "TRACE-LIVE-ONE-SHOT-20260811",
  "video_uri": "data_mock/data1/front_camera.mp4",
  "log_uri": "data_mock/data1/vehicle_state.csv",
  "analysis_prompt": "Phân tích sự cố giao thông trong toàn bộ video. Xác định t_start, t0, t_end, timeline và các claim chỉ dựa trên bằng chứng quan sát được; không dùng các file ground truth.",
  "metadata": {
    "trace": "one-shot-live-qwen",
    "ground_truth_supplied_to_model": false
  }
}
```

Validator kiểm tra prompt length, path root, file existence/size và duration ở [`incident_runtime.py:70-81`](../src/services/incident_runtime.py#L70). Initial graph state được tạo tại [`workflow.py:64-81`](../src/services/workflow.py#L64).

---

## 4. Request/response Qwen thật

### 4.1 Request

| Thuộc tính | Giá trị |
|---|---|
| Request count | **1** |
| Model | `qwen3-vl-flash` |
| Role | `user` |
| Video transport | `data:video/mp4;base64` |
| Video decoded bytes | `930,891` |
| Video FPS gửi provider | `9.0` |
| Prompt length | `9,946` ký tự |
| Prompt SHA-256 | `96086314af5fa8b130fda1b589e8740bd036ef9ed46aae01ac3537b97aa511b8` |
| Base prompt | `5,517` ký tự |
| JSON Schema | `4,231` ký tự |
| Temperature | `0.0` |
| Timeout | `120s` |
| Response format | `json_object` |
| Thinking | tắt |

Prompt được tạo từ [`video_analysis.py:21-109`](../src/prompts/video_analysis.py#L21), nối với `VideoMemory.model_json_schema()` tại [`vlm.py:361-375`](../src/services/vlm.py#L361). Các quy tắc đáng chú ý:

- Ép giả định camera trước gắn cứng trên xe ego.
- Tìm va chạm/road departure và theo dõi toàn chuỗi.
- Yêu cầu `t_start <= t0 <= t_end`.
- Yêu cầu 3–6 timeline event và claim có evidence.
- Yêu cầu dùng “frame_id đã được cung cấp”, dù native-video request thực tế không cung cấp frame ID nào. Đây là gốc của COR-01.
- Nối schema `VideoMemory`, schema lại cho phép `verification_status` nhận cả `supported`, `contradicted`, `unverified`. Đây là gốc của COR-02.

### 4.2 Response provider raw

- Response ID: `chatcmpl-a7c31c2a-ee09-9988-b0a3-b7e66ca76d21`.
- Finish reason: `stop`.
- Response length: `3,967` ký tự.
- Provider duration quan sát: `14,764 ms`.
- Usage: `13,634 + 1,172 = 14,806` token.

Tóm tắt structured output raw:

```json
{
  "incident_window": {"t_start": 5.0, "t0": 7.0, "t_end": 17.0},
  "representative_timestamp_s": 7.0,
  "analysis_mode": "native_video (backend default injection)",
  "timeline": [
    {"timestamp_s": 5.0, "evidence_ids": ["frame_5"]},
    {"timestamp_s": 6.0, "evidence_ids": ["frame_6"]},
    {"timestamp_s": 7.0, "evidence_ids": ["frame_7"]},
    {"timestamp_s": 9.0, "evidence_ids": ["frame_9"]},
    {"timestamp_s": 17.0, "evidence_ids": ["frame_17"]}
  ],
  "claims": [
    {
      "claim_id": "claim_1",
      "timestamp_s": 6.0,
      "verification_status": "supported",
      "evidence": [{"evidence_id": "frame_6", "timestamp_s": 6.0}]
    },
    {
      "claim_id": "claim_2",
      "timestamp_s": 7.0,
      "verification_status": "supported",
      "evidence": [{"evidence_id": "frame_7", "timestamp_s": 7.0}]
    },
    {
      "claim_id": "claim_3",
      "timestamp_s": 17.0,
      "verification_status": "supported",
      "evidence": [{"evidence_id": "frame_17", "timestamp_s": 17.0}]
    }
  ]
}
```

Raw response mô tả:

- `5s`: xe ego tiến thẳng, xe tải bên phải, xe ngược chiều bên trái.
- `6s`: đổi hướng sang phải, gần xe tải/xe sedan.
- `7s`: “va chạm mạnh với lan can bên phải”, bắt đầu rơi.
- `9s`: đã rơi khỏi cầu.
- `17s`: chìm trong nước, không còn di chuyển.

Backend sau đó gọi [`reconcile_native_video_evidence`](../src/services/video_memory.py#L376), gắn thêm `frame_5` vào `claim_1` và `frame_9` vào `claim_2`. Tổng evidence trong draft report trở thành:

```text
frame_6, frame_5, frame_7, frame_9, frame_17
```

Đây đều không phải tên file artifact thực.

---

## 5. Trace input/output từng node

Graph và edge được khai báo tại [`incident_graph.py:133-155`](../src/agents/incident_graph.py#L133).

```text
START
  → analyze_video
  → cut_incident_video
  → analyze_log
  → verify
  → draft_report
  → review (interrupt)
```

`auto_reanalyze`, `manual_reanalyze`, `manual_verify` và `cleanup` không chạy trong one-shot này.

### 5.1 Pre-graph input validation

**Input:** `IncidentCreateRequest` ở mục 3.

**Checks:**

- Prompt không vượt 5,000 ký tự.
- Video/log nằm trong `INCIDENT_INPUT_ROOTS` hoặc upload root.
- File tồn tại, là regular file, không vượt size.
- Probe video thành công và duration không quá 60s.

**Output:** request hợp lệ; initial state:

```json
{
  "status": "running",
  "auto_reanalysis_count": 0,
  "manual_reanalysis_count": 0,
  "artifact_uris": {},
  "warnings": [],
  "review_audit": [],
  "model_activities": []
}
```

### 5.2 Node `analyze_video`

**Source:** [`incident.py:113-188`](../src/agents/nodes/incident.py#L113)

**Input fields thực sự đọc:**

- `incident_id`
- `video_uri`
- `analysis_prompt`
- workflow config/provider capability

`metadata` do API client gửi không được node đọc.

**Local preprocessing output:**

```json
{
  "duration_s": 17.0,
  "width": 512,
  "height": 288,
  "fps": 15.0,
  "mime_type": "video/mp4",
  "size_bytes": 930891,
  "sha256": "f9a6f8f6c99a7dcf4a448f18b4db51f2ca97ff465cd865246674fa79d9001e32"
}
```

**External I/O:** request/response ở mục 4.

**Output delta:**

```json
{
  "status": "running",
  "video_memory": "VideoMemory(window=5..7..17, 4 entities, 5 timeline, 3 claims)",
  "claims": ["claim_1", "claim_2", "claim_3"],
  "remote_media_handles": [],
  "artifact_uris.normalized_video": "/tmp/incident-one-shot-ujs95j3k/artifacts/TRACE-LIVE-ONE-SHOT-20260811/normalized.mp4",
  "model_activity": {
    "provider": "qwen",
    "model": "qwen3-vl-flash",
    "status": "completed",
    "duration_ms": 14764,
    "total_tokens": 14806
  }
}
```

### 5.3 Node `cut_incident_video`

**Source:** [`incident.py:191-248`](../src/agents/nodes/incident.py#L191)

**Input:** `incident_id`, source `video_uri`, `video_memory.incident_window=[5,7,17]`, media config.

**Behavior:**

- Clip có pre-roll 1s và post-roll 2s, nhưng bị chặn bởi source duration 17s.
- Effective clip xấp xỉ `[4,17]`.
- Sample incident frames trong `[5,17]` ở 4 FPS.
- Chọn frame gần `representative_timestamp_s=7.0` nhất.

**Output delta:**

| Artifact | Kết quả |
|---|---|
| `incident_clip` | 4,819,597 byte; SHA-256 `bd558a51478a7cd46444656e181b61e1f231560d6470d17838be65df9bc6f8b0` |
| `incident_frames` | 48 JPEG |
| `representative_frame` | `frame-000009.jpg`, 13,973 byte |
| Representative SHA-256 | `942b21d5450effbc7e51c9f199c57d7b22091a7315138244cb76b662eaf5c091` |

Visual inspection của `frame-000009.jpg` cho thấy xe ego vẫn trên cầu, xe màu đen rất gần bên trái và xe tải phía trước; frame chưa thể hiện rõ cảnh “va chạm mạnh với lan can” mà Qwen gắn tại `7s`.

### 5.4 Node `analyze_log`

**Source:** [`incident.py:251-299`](../src/agents/nodes/incident.py#L251), implementation [`log_analysis.py:77-149`](../src/services/log_analysis.py#L77)

**Input:**

- `log_uri=data_mock/data1/vehicle_state.csv`
- window `[5.0, 17.0]`
- brake rise threshold `0.3`
- steering change threshold `10.0`

**Output:**

```json
{
  "row_count": 25,
  "speed_start": 41.5,
  "speed_end": 0.0,
  "speed_min": 0.0,
  "speed_max": 41.5,
  "max_deceleration": -3.611111111111111,
  "max_brake": 1.0,
  "brake_rise_time": 6.0,
  "max_steering_change": 0.36000000000000004,
  "events": [
    {"type": "brake_rise", "timestamp_s": 6.0, "delta": 0.32},
    {"type": "brake_rise", "timestamp_s": 6.5, "delta": 0.33}
  ],
  "steering_change_events": 0,
  "warnings": [],
  "errors": []
}
```

**Artifacts:**

- `log_slice.csv`: 25 data rows + header, 1,235 byte.
- `01_speed_acceleration.png`: 65,724 byte.
- `02_brake_throttle.png`: 58,618 byte.
- `03_steering.png`: 46,757 byte.
- `04_autonomy_events.png`: 38,364 byte.

State cũng lưu đồng thời `log_analysis`, `log_evidence_summary`, `log_events`, `chart_uris` và toàn bộ URI trong `artifact_uris`; một phần là dữ liệu lặp.

### 5.5 Node `verify`

**Source:** [`incident.py:302-356`](../src/agents/nodes/incident.py#L302), prompt [`verification.py:8-53`](../src/prompts/verification.py#L8)

**Input:** 3 claims + log URI + log summary + tolerance `0.5s`.

**Per-claim deterministic context:**

| Claim | Timestamp | Sample window | Samples | Allowed direct evidence | Điểm nổi bật |
|---|---:|---:|---:|---|---|
| `claim_1` | 6.0 | 4.5–7.5 | 7 | `log-row:5.5`, `6`, `6.5` | speed 42.2→21.5; brake 0.12→1; steer 0.03→0.9 |
| `claim_2` | 7.0 | 5.5–8.5 | 7 | `log-row:6.5`, `7`, `7.5` | speed 40.8→12.5; brake max 1; steer max 0.9 |
| `claim_3` | 17.0 | 15.5–17.0 | 4 | `log-row:16.5`, `17` | speed 0→0; không chứng minh được “xe chìm” |

**Provider boundary:** không gọi OpenAI thật. Local response trả cho cả 3:

```json
{
  "status": "unverified",
  "reason": "Provider verification được thay bằng response cục bộ trong one-shot trace.",
  "evidence_ids": []
}
```

**Output delta:**

- `verification.results`: 3 `unverified`.
- `claim_log_summaries`: 3 structured summary.
- `video_memory.claims[*].verification_status`: bị đổi từ raw Qwen `supported` thành `unverified`.
- `claims`: danh sách đã normalize trạng thái.
- `status`: vẫn `running`.

Vì không có `contradicted`, route đi thẳng tới `draft_report`. `auto_reanalysis_enabled=false` cũng ngăn retry tự động.

### 5.6 Node `draft_report`

**Source:** [`incident.py:445-543`](../src/agents/nodes/incident.py#L445)

**Input:** video memory, verification, log evidence, artifact URIs, warnings.

**Provider boundary:** report provider không gọi mạng; trả narrative cục bộ.

**Backend overwrite sau provider:**

- `summary` luôn bị thay bằng `memory.video_summary` nếu có.
- Vì có log, `log_findings` bị thay bằng deterministic log summary.
- Vì có log, `alignment` bị thay bằng `_verification_alignment(...)`.

**Output:** `DraftReport` đủ 10 section, `review_status=pending`, state chuyển sang `awaiting_review`.

Các giá trị chính:

```json
{
  "incident_window": {"t_start": 5.0, "t0": 7.0, "t_end": 17.0},
  "has_log": true,
  "timeline_event_count": 5,
  "claim_log_summary_count": 3,
  "verification_result_count": 3,
  "evidence_count": 5,
  "artifact_count": 9,
  "warnings": [],
  "review_status": "pending"
}
```

### 5.7 Node `review`

**Source:** [`review.py:12-68`](../src/agents/nodes/review.py#L12)

**Input interrupt payload:**

```json
{
  "incident_id": "TRACE-LIVE-ONE-SHOT-20260811",
  "report": "DraftReport 10 section",
  "artifacts": "9 URI",
  "claims": "3 claims, đều unverified sau node verify",
  "warnings": [],
  "actions": ["approve", "edit", "reanalyze", "not_incident"]
}
```

**Output:** graph suspend tại interrupt; không có review decision; trạng thái giữ `awaiting_review`.

### 5.8 Các node không chạy

| Node | Điều kiện kích hoạt | Trạng thái one-shot |
|---|---|---|
| `auto_reanalyze` | Có claim `contradicted`, count < 1 và feature enabled | Không chạy |
| `manual_reanalyze` | Reviewer chọn `reanalyze` với feedback + target IDs | Không chạy |
| `manual_verify` | Manual reanalysis và incident có log | Không chạy |
| `cleanup` | Terminal hoặc failed | Không chạy vì đang review |

Contracts nằm tại [`incident.py:359-443`](../src/agents/nodes/incident.py#L359), routing tại [`incident_graph.py:109-131`](../src/agents/incident_graph.py#L109).

---

## 6. Đối chiếu kết quả với dữ liệu tham chiếu

### 6.1 So sánh timestamp

| Mốc | Qwen one-shot | `incident.json` / human annotation | Sai lệch |
|---|---:|---:|---:|
| `t_start` | 5.0 | 6.0 | -1.0s |
| `t0` | 7.0 | event “collision/evasive” 6.8 | +0.2s |
| barrier departure | Qwen mô tả tại 7.0 | 7.5 | -0.5s |
| fall from bridge | 9.0 | 9.0 | 0s |
| water impact | không tách riêng | 13.5 | thiếu event |
| `t_end` | 17.0 | 14.5 | +2.5s |

Ground truth `data1` là “provisional manual ground truth”, nên bảng trên là đối chiếu chứ không phải tuyệt đối. Tuy nhiên có hai vấn đề nội tại rõ:

1. Qwen nói va lan can tại `7.0`, nhưng representative frame `7.0` chưa thể hiện va lan can; frame cho thấy critical proximity.
2. Qwen không tách water impact `13.5`, rồi dùng scene end `17.0` làm claim kết cục.

### 6.2 Đối chiếu log

Kết quả log có tính toán nội bộ nhất quán:

- Brake bắt đầu tăng mạnh tại 6.0–6.5s.
- Speed giảm 41.5→0 km/h trong window.
- Steer tăng 0.03→0.9 quanh critical phase.
- Qwen đặt `t0=7.0`, gần vùng brake/steer mạnh.

Nhưng log không có collision sensor và không quan sát ngoại cảnh; đúng theo prompt verification, nó không đủ để xác nhận claim “va lan can”, “rơi khỏi cầu” hoặc “chìm”.

---

## 7. Lỗ hổng bảo mật

### SEC-01 — Credential có hình thức khóa thật trong file được commit

**Mức độ: Critical**

[` .env.example:117-119`](../.env.example#L117) chứa `AI_LOG_SERVER`, một `AI_LOG_API_KEY` dài có hình thức credential thật và output directory. File này được Git theo dõi.

Không kiểm tra validity của key vì việc đó không được phép. Cần coi key đã lộ:

1. Rotate/revoke ngay tại dịch vụ AI log.
2. Thay bằng placeholder như `AI_LOG_API_KEY=replace-me`.
3. Kiểm tra Git history và provider usage/audit log.
4. Nếu key từng có quyền ghi rộng, kiểm tra dữ liệu/log giả mạo.

### SEC-02 — Không auth/authorization/rate limit trên API tốn phí và destructive

**Mức độ: Critical**

Router expose upload, create, list, get, delete và review tại [`api/incidents.py:44-127`](../src/api/incidents.py#L44), không dependency xác thực nào. README cũng thừa nhận thiếu auth tại [`README.md:168`](../README.md#L168).

Tác động nếu bind ra internet (`Dockerfile`/compose expose port 8000):

- Bất kỳ ai upload video tới disk.
- Bất kỳ ai tạo workflow và tiêu quota Qwen/OpenAI.
- Bất kỳ ai liệt kê incident IDs và đọc report/claim/artifact path.
- Bất kỳ ai approve/edit/reanalyze/not_incident.
- Bất kỳ ai xóa incident đang chờ review hoặc terminal.
- Không rate limit nên có thể gây cost denial-of-service và disk exhaustion.

Khuyến nghị tối thiểu: auth token/JWT, authorization theo tenant/incident, request rate limit, quota theo user, giới hạn concurrent job và audit actor từ identity server-side thay vì tin `reviewer` do client gửi.

### SEC-03 — Metadata và dữ liệu incident có thể bị lộ qua list/get

**Mức độ: High**

`GET /incidents` trả mọi ID; `GET /incidents/{id}` trả summary, claims, report, warnings và artifact URI. Khi không auth, ID không còn là bí mật. Dù raw state/prompt/API key không trả ra, đây vẫn là dữ liệu sự cố nhạy cảm.

### SEC-04 — Endpoint chat trả exception string và trường `analysis`

**Mức độ: Medium**

[`api/routes.py:11-21`](../src/api/routes.py#L11) trả `HTTPException(detail=str(e))`, khác với incident router đã sanitize lỗi. [`models/schemas.py:8-10`](../src/models/schemas.py#L8) còn expose trường `analysis`.

Hiện chat agent chỉ là placeholder, nhưng nếu nối LLM/tool thật, pattern này có thể lộ provider errors, path, prompt hoặc thông tin nội bộ.

### SEC-05 — Streamlit base URL tùy ý tạo SSRF nếu UI được deploy

**Mức độ: Medium**

[`main_test.py:58`](../main_test.py#L58) cho người dùng nhập arbitrary base URL; [`main_test.py:15-29`](../main_test.py#L15) khiến server Streamlit gọi URL đó. Nếu UI public, attacker có thể khiến host Streamlit gọi dịch vụ nội bộ.

Khuyến nghị: cấu hình base URL server-side/allowlist scheme+host, không cho người dùng public nhập tùy ý.

### SEC-06 — Reviewer identity do client tự khai

**Mức độ: Medium**

`ReviewDecision.reviewer` chỉ là chuỗi bắt buộc tại [`models/api.py:67-104`](../src/models/api.py#L67). Không có identity binding nên audit trail có thể bị giả mạo.

---

## 8. Lỗi correctness và evidence

### COR-01 — Evidence native-video không có provenance thật

**Mức độ: High**

Trong native mode, model nhận video nhưng không nhận manifest/frame IDs. Prompt vẫn bảo dùng frame ID “đã được cung cấp” tại [`video_analysis.py:92-96`](../src/prompts/video_analysis.py#L92). Qwen bịa `frame_5`, `frame_6`, ...

[`reconcile_native_video_evidence`](../src/services/video_memory.py#L376):

- Giữ nguyên evidence ID do model trả.
- Nếu claim không có evidence, tự tạo `native-evidence:{claim_id}`.
- Nếu timeline dùng ID lạ, tự gắn ID đó vào claim gần timestamp nhất.

[`validate_video_memory`](../src/services/video_memory.py#L291) chỉ kiểm tra ID nội bộ nhất quán; với native mode `source_frame_ids=None`, nó không thể kiểm tra ID có artifact thật.

Trong run:

- Model IDs: `frame_5`, `frame_6`, `frame_7`, `frame_9`, `frame_17`.
- File thật: `frame-000001.jpg` đến `frame-000048.jpg`.
- Không có mapping trong state/report từ model ID tới URI ảnh.

Khuyến nghị: sau Qwen response, map mỗi evidence timestamp tới frame artifact thật gần nhất và thay bằng canonical ID/URI; không tự tạo evidence “có vẻ thật” nếu không có artifact.

### COR-02 — VLM được phép tự pre-verify claim

**Mức độ: High**

`Claim.verification_status` cho phép mọi enum tại [`models/incidents.py:125-130`](../src/models/incidents.py#L125). Qwen raw trả `supported` cho cả 3 claim. [`validate_video_memory`](../src/services/video_memory.py#L291) không ép về `unverified`.

Trong incident có log, node verify ghi đè trạng thái nên one-shot cuối cùng an toàn hơn. Nhưng trong video-only path (`cut → draft_report`) không có verify; `supported` do VLM tự gắn có thể xuất hiện trực tiếp trong API/UI.

Khuyến nghị:

- Loại `verification_status` khỏi schema output VLM, hoặc
- Luôn normalize tất cả claim về `UNVERIFIED` ngay sau model output, trước routing, và
- Thêm test video-only dùng provider response cố tình trả `supported`.

### COR-03 — Steering threshold sai đơn vị

**Mức độ: High**

Alias `STEERING_ALIASES` trộn `steering_angle` và `steer` tại [`log_analysis.py:26`](../src/services/log_analysis.py#L26). Một threshold chung `10.0` được so trực tiếp tại [`log_analysis.py:173-185`](../src/services/log_analysis.py#L173).

Với `steering_angle` đơn vị độ, `10` có thể hợp lý. Với `steer` normalized `[-1,1]`, `10` là bất khả thi. Run thật có:

- steer 0.03→0.9;
- max step change 0.36;
- zero `steering_change` event.

Khuyến nghị: phân biệt field/unit; ví dụ threshold độ cho `steering_angle`, threshold normalized khoảng 0.2–0.3 cho `steer`, hoặc normalize tất cả về một unit trước detection.

### COR-04 — `t0` và narrative không nhất quán với representative frame

**Mức độ: High về chất lượng kết quả**

Qwen đặt `t0=7.0` và nói va lan can mạnh. Frame gần 7s nhất cho thấy close encounter, chưa cho thấy lan can impact. Human data đánh dấu `collision_or_evasive_maneuver=6.8`, `barrier_departure=7.5`, `fall=9.0`.

Đây có thể là conflation giữa close encounter/collision với oncoming vehicle và road departure. Validator chỉ kiểm tra timestamp range/order, không kiểm tra semantic alignment.

Khuyến nghị: second-stage temporal verification bằng sampled frames quanh `t0`, hoặc yêu cầu evidence canonical và reject khi representative frame không hỗ trợ mô tả chính.

### COR-05 — Timeline/claim/evidence không bắt buộc nằm trong incident window

**Mức độ: Medium**

[`validate_video_memory:319-333`](../src/services/video_memory.py#L319) chỉ bắt timestamp nằm trong source duration; chỉ representative timestamp phải nằm trong incident window. Timeline/claim/evidence có thể nằm ngoài `[t_start,t_end]` mà vẫn pass.

Nếu định nghĩa window là toàn bộ sự cố, đây là invariant còn thiếu.

### COR-06 — Report model sinh output nhưng backend ghi đè

**Mức độ: Medium / cost correctness**

Trong case có log, [`incident.py:486-496`](../src/agents/nodes/incident.py#L486) ghi đè:

- `summary`
- `log_findings`
- `alignment`

Trong case không log, ít nhất `summary` và `log_findings` bị ghi đè. Nhưng prompt/report schema vẫn yêu cầu model sinh tất cả 6 narrative field tại [`prompts/reporting.py:39-50`](../src/prompts/reporting.py#L39).

Khuyến nghị: chỉ yêu cầu model sinh field thực sự dùng, hoặc bỏ report call nếu deterministic assembly đã đủ.

### COR-07 — `video_observations.observations` luôn rỗng

**Mức độ: Low/Medium**

Model có `Observation` và report section có `observations`, nhưng draft node chỉ truyền narrative tại [`incident.py:518-520`](../src/agents/nodes/incident.py#L518). Không có node nào tạo structured observation.

### COR-08 — Auto-reanalysis retry có thể tăng số request ngoài dự kiến

**Mức độ: Medium / cost**

Normal config cho phép Qwen structured-output retry `VLM_MAX_RETRIES=2`, nghĩa là một operation có thể gọi provider tối đa 3 lần tại [`vlm.py:377-432`](../src/services/vlm.py#L377). Nếu verification trả conflict, graph còn gọi auto-reanalysis và verify lại.

Một “workflow run” có thể phát sinh nhiều provider request. Cần ghi rõ budget/request count và telemetry theo attempt.

---

## 9. Lỗi dữ liệu và test

### DATA-01 — Ground truth `INC_LOSS_CONTROL_001` vi phạm thứ tự thời gian

**Mức độ: High**

[`data_mock/INC_LOSS_CONTROL_001/incident.json:8-13`](../data_mock/INC_LOSS_CONTROL_001/incident.json#L8):

```json
{"t_start": 20.0, "t0": 2.75, "t_end": 26.3}
```

Điều này vi phạm `t_start <= t0 <= t_end` trong [`IncidentWindow`](../src/models/incidents.py#L43). Collision 2.75 còn xuất hiện trước trigger loss-of-control 20.0. Human annotation lặp cùng lỗi tại [`human_annotation.json:9-12`](../data_mock/INC_LOSS_CONTROL_001/human_annotation.json#L9), thậm chí evidence có `start_time=20.0`, `end_time=3.75`.

Khả năng cao `2.75` phải là `24.75` hoặc timestamp bị mất prefix, nhưng không nên sửa bằng suy đoán; cần regenerate/verify từ frame 71898 và FPS.

### TEST-01 — 41/165 test thất bại

**Mức độ: High**

Kết quả:

```text
41 failed, 124 passed in 0.79s
```

Hai nhóm chính:

1. **11 failure do fixture path bị di chuyển nhưng code/test/docs chưa cập nhật.** Test và README dùng `data_mock/front_camera.mp4`, `data_mock/vehicle_state.csv`; file thật nằm trong `data_mock/data1/` hoặc `data_mock/INC_LOSS_CONTROL_001/`.
2. **30 failure do contract/test drift.** Test vẫn tạo `Claim(evidence_ids=...)`, `VideoMemory(source_frame_ids=...)`, `EvidenceReference(kind=..., artifact_uri=...)`, hoặc gọi `build_human_reanalysis_prompt(current_evidence=...)`, trong khi model/function hiện tại đã đổi signature/schema.

Các cụm failure:

| Cụm | Số lượng | Nguyên nhân chủ đạo |
|---|---:|---|
| Incident graph E2E | 3 | Missing root fixture |
| Incident node | 3 | Contract/behavior drift |
| Reanalysis prompt | 5 | Signature drift |
| Reporting prompt | 3 | `Claim.evidence_ids` không còn tồn tại |
| Chart/log/media | 8 | Missing root fixture |
| Reporting service | 5 | Old Claim schema |
| Video memory | 14 | Old evidence/source-frame schema |

Không nên “sửa test để pass” trước khi quyết định contract nào là canonical. Actual run chứng minh contract mới vẫn có lỗi provenance.

### TEST-02 — Ruff format check thất bại

`ruff check` pass, nhưng `ruff format --check src tests main_test.py` báo 13 file chưa format, gồm source và test. Không sửa vì phạm vi chỉ cho phép report/test harness.

### TEST-03 — Checkpoint phát warning future incompatibility

Khi đọc history, LangGraph cảnh báo deserialize các type chưa đăng ký như `VideoMemory`, `Claim`, `VerificationStatus`, `DraftReport`, `ModelActivity`. Warning nói future version sẽ block nếu strict msgpack.

Checkpointer được tạo tại [`incident_runtime.py:174-180`](../src/services/incident_runtime.py#L174). Cần pin/test version hoặc đăng ký allowed modules theo API LangGraph hiện hành.

### TEST-04 — README và tài liệu dùng path không tồn tại

README request sample tại [`README.md:93-97`](../README.md#L93) dùng root files không còn tồn tại. Nhiều tài liệu agent backend và test lặp path này.

### TEST-05 — `ARCHITECTURE.md` vẫn là boilerplate sai hệ thống

[`ARCHITECTURE.md`](../ARCHITECTURE.md) mô tả React/Next.js, vector store và placeholders, trong khi hệ thống thật là FastAPI + Streamlit + LangGraph + SQLite, không dùng vector store.

---

## 10. Reliability, concurrency và vận hành

### REL-01 — Health check báo xanh khi workflow startup lỗi

**Mức độ: Medium**

Lifespan catch mọi startup exception và vẫn yield app tại [`main.py:24-34`](../src/main.py#L24). `/health` luôn trả `{"status":"ok"}` tại [`main.py:65-67`](../src/main.py#L65). Docker healthcheck vì vậy không phát hiện missing key, DB/checkpointer lỗi hoặc runtime configuration lỗi.

Khuyến nghị: tách `/live` và `/ready`; readiness phải kiểm tra `incident_workflow_service` tồn tại.

### REL-02 — Workflow synchronous trong HTTP request

**Mức độ: Medium/High**

`POST /incidents` await toàn bộ `service.create`, model/media/log/report rồi mới trả 202. UI phải dùng thread riêng. `background_concurrency` tồn tại nhưng không được dùng.

Tác động: timeout proxy/client, khó cancel, worker bị giữ lâu, concurrency không kiểm soát.

### REL-03 — Async checkpointer gọi SQLite sync trực tiếp

**Mức độ: Medium**

[`DirectAsyncSqliteSaver`](../src/services/incident_runtime.py#L38) bọc sync methods trong `async def` nhưng không offload thread; I/O vẫn block event loop. Một connection dùng chung với `check_same_thread=False`.

### REL-04 — Multi-worker/concurrent access chưa an toàn

**Mức độ: Medium**

Workflow state/locks/audit nằm trong process memory; SQLite connection/checkpoint model phù hợp demo single process. `delete()` cũng không lấy per-incident review lock, nên delete/review có race tiềm ẩn.

### REL-05 — Remote cleanup bị hard-disable

**Mức độ: Medium**

Dependency default `cleanup_remote_resources=True` tại [`incident_graph.py:44`](../src/agents/incident_graph.py#L44), nhưng runtime luôn truyền `False` tại [`incident_runtime.py:171`](../src/services/incident_runtime.py#L171). Với provider tạo remote handles, cleanup node không release resource.

### REL-06 — Model activity registry tăng không giới hạn

**Mức độ: Low/Medium**

[`ModelActivityRegistry`](../src/services/model_observability.py#L13) không có eviction/delete. `_finish` còn scan toàn bộ incident/activity để tìm activity ID, chi phí tăng tuyến tính theo tuổi process.

### REL-07 — Artifact và state không có lifecycle retention

**Mức độ: Medium**

Delete xóa checkpoint/report nhưng không xóa normalized video, clip, frames, charts hoặc upload source. Disk sẽ tăng theo thời gian; dữ liệu nhạy cảm còn tồn tại sau khi API báo deleted.

---

## 11. Code dư, biến/state dư và duplication

### 11.1 Code/module không được production path sử dụng

| Vị trí | Thành phần | Bằng chứng |
|---|---|---|
| [`src/services/llm.py`](../src/services/llm.py) | `get_llm()` | Không có caller trong `src`, `tests`, `main_test.py` |
| [`src/agents/tools/example_tool.py`](../src/agents/tools/example_tool.py) | `search_knowledge`, `calculate`, `_eval_node` | Không được graph/router import |
| [`src/prompts/reanalysis.py:14-35`](../src/prompts/reanalysis.py#L14) | `build_auto_reanalysis_prompt` single-claim | Production dùng plural `build_auto_reanalysis_prompt_for_conflicts`; single version chỉ còn tests/export |
| [`main_test.py:177-204`](../main_test.py#L177) | `_upload_and_start` sync | UI chỉ gọi `_upload_and_start_async` tại line 79 |

Nếu giữ endpoint `/chat` placeholder thì `src/agents/graph.py`, `state.py`, `nodes/example_node.py` vẫn đang dùng; chúng không hoàn toàn dead. Tuy nhiên đây là demo echo, không phải incident system.

### 11.2 Config dư/không có consumer

| Field | Vị trí | Ghi chú |
|---|---|---|
| `background_concurrency` | [`config.py:104`](../src/config.py#L104) | Không có reference ngoài khai báo |
| `database_url` | [`config.py:107`](../src/config.py#L107) | Incident persistence dùng `incident_database_path` |
| `chroma_persist_dir` | [`config.py:110`](../src/config.py#L110) | Không có vector store implementation |
| `model_name`, `llm_temperature` | [`config.py:29-30`](../src/config.py#L29) | Chỉ được dead `get_llm()` đọc; `/chat` hiện không gọi LLM |

Các biến `.env.example` tương ứng DATABASE_URL/CHROMA làm người vận hành tưởng tính năng tồn tại.

### 11.3 State dư hoặc lặp

| State field | Vị trí ghi | Consumer | Nhận xét |
|---|---|---|---|
| API `metadata` | [`workflow.py:73`](../src/services/workflow.py#L73) | Không có node nào đọc | Persist dữ liệu tùy ý không cần thiết; có thể chứa PII |
| `chart_uris` | [`incident.py:291`](../src/agents/nodes/incident.py#L291) | Không consumer | Trùng `artifact_uris.chart_*` |
| `log_events` | [`incident.py:290`](../src/agents/nodes/incident.py#L290) | Không consumer trực tiếp | Trùng `log_analysis.events` và `log_evidence_summary.events` |
| `claims` | nhiều node | snapshot/report | Trùng `video_memory.claims`, nhưng dùng để public access; dễ drift |
| `report_narrative` | draft node | terminal evidence collection | Phần lớn trùng nội dung đã nằm trong `draft_report` |

### 11.4 Biến cục bộ/loop variable dư hoặc đặt tên sai

[`model_observability.py:75`](../src/services/model_observability.py#L75) lặp `for incident_id, activities ...` nhưng `incident_id` không dùng. Nên đổi `_incident_id` hoặc duy trì index trực tiếp từ activity ID để tránh scan.

### 11.5 Duplication chức năng

- `_upload_and_start` và `_upload_and_start_async` lặp upload + payload assembly.
- `claims` tồn tại ở state root và trong `video_memory`.
- Log events/metrics tồn tại qua 3 representation.
- Report model sinh narrative sau đó deterministic backend ghi đè một nửa.
- `ARCHITECTURE.md`, `docs/agent_backend/*`, README và code mô tả nhiều kiến trúc khác nhau.

---

## 12. Những điểm làm đúng

Để đánh giá cân bằng, các phần sau hoạt động tốt trong one-shot:

- Path validation dùng `.resolve()` và `is_relative_to`, giảm path traversal.
- Upload đổi tên UUID, chỉ lấy basename, stream theo chunk và cleanup partial file.
- Incident error router sanitize message tốt hơn chat route.
- Video được normalize nhỏ từ 6.7 MB xuống 0.93 MB trước provider.
- Timestamp/schema validation chặn output ngoài 0–17s.
- Log slicing/metric deterministic và kết quả khớp CSV.
- Verification prompt giới hạn evidence IDs theo claim/tolerance.
- Report backend sở hữu timestamp, metric, artifact và review status.
- Public snapshot không chứa API key/raw prompt/remote handle.
- One-shot guard đã chứng minh request count Qwen bằng 1.
- `ruff check` pass và `pip check` không phát hiện dependency broken.

---

## 13. Thứ tự sửa đề xuất

### P0 — Làm ngay

1. Rotate credential ở `.env.example`, purge/assess Git history.
2. Không expose service ra internet trước khi có auth + authorization + rate limit/quota.
3. Canonicalize native evidence timestamp → artifact frame thật; cấm fabricated IDs.
4. Ép VLM claim về `unverified` trước verification.
5. Quyết định schema canonical rồi đồng bộ 41 test failures.
6. Sửa/regenerate `INC_LOSS_CONTROL_001` ground truth.

### P1 — Trước demo đánh giá chất lượng

1. Tách steering unit và threshold.
2. Thêm temporal evidence check quanh `t0`.
3. Sửa tất cả fixture path/README commands.
4. Bỏ các report fields sẽ bị overwrite khỏi model prompt.
5. Readiness health check thật.
6. Pin dependency/lock file và giải quyết LangGraph msgpack warning.

### P2 — Trước production

1. Queue/background worker; idempotency; controlled concurrency/cancellation.
2. Database/checkpointer production-grade, migration/versioning.
3. Artifact object storage, access control, retention và delete cascade.
4. Tenant isolation và server-derived reviewer identity.
5. Structured observability per provider attempt/cost.
6. Xóa dead code/config và thống nhất architecture docs.

---

## 14. Lệnh kiểm tra và kết quả

```text
.venv/bin/ruff check src tests main_test.py
→ PASS

.venv/bin/ruff format --check src tests main_test.py
→ FAIL: 13 files would be reformatted

.venv/bin/pytest tests -q --tb=no
→ 41 failed, 124 passed

.venv/bin/pip check
→ No broken requirements found

.venv/bin/python -m py_compile api_node_trace_test.py
.venv/bin/ruff check api_node_trace_test.py
.venv/bin/ruff format --check api_node_trace_test.py
→ PASS

.venv/bin/python api_node_trace_test.py
→ PASS; Qwen external request_count=1; final status=awaiting_review
```

Không chạy `pip-audit`/SCA network-based; báo cáo không tuyên bố dependency không có CVE.

---

## 15. Artifact inventory của run

Runtime artifacts nằm ngoài repository tại:

```text
/tmp/incident-one-shot-ujs95j3k/
```

Inventory:

- 1 normalized video.
- 1 incident clip.
- 48 incident JPEG frames.
- 1 log slice CSV.
- 4 PNG charts.
- 1 checkpoint SQLite.
- 1 empty/non-terminal report SQLite schema.

Thư mục `/tmp` là tạm thời và có thể mất sau reboot/cleanup. Không có artifact runtime nào được commit.

---

## 16. File test harness

[`api_node_trace_test.py`](../api_node_trace_test.py) có các guard sau:

- Chỉ cho `OneShotCompletions.create()` chạy một lần.
- Request thứ hai ném lỗi ngay.
- `vlm_max_retries=0`.
- `auto_reanalysis_enabled=false`.
- Downstream OpenAI clients là local doubles.
- Secret không được in.
- Base64 video không được in; chỉ size/hash.
- Tất cả DB/artifact runtime nằm dưới `/tmp`.

Không chạy lại script nếu không muốn phát sinh thêm một request thật. Muốn dùng lại cho dry-run cần bổ sung mode replay/mock trước.

---

## 17. Kết luận cuối

Pipeline chứng minh được khả năng chạy end-to-end đến human review và tạo đầy đủ media/log/chart/report artifacts. Tuy nhiên ba thuộc tính cốt lõi chưa đạt:

1. **Security:** API public không có identity/quota, và repository có credential nghi bị lộ.
2. **Evidence integrity:** native evidence hiện là ID do model tạo, không phải bằng chứng truy vết được; VLM còn có thể tự pre-verify.
3. **Regression confidence:** 24.8% test suite đang fail và ground truth chính có timestamp tự mâu thuẫn.

Vì vậy không nên approve báo cáo AI tự động hoặc expose backend cho người dùng thật trước khi hoàn thành tối thiểu nhóm P0.
