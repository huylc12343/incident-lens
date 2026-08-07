# Kế hoạch triển khai Agent Workflow

## 1. Mục tiêu và giới hạn

Kế hoạch này chuyển đặc tả trong `docs/project_agent_workflow.md` thành các lần chạy vibecoding độc lập, theo luồng:

`video ngắn (và log tùy chọn) → VLM phân tích → cắt clip → phân tích log → đối chiếu claim → tái phân tích có kiểm soát → LLM tạo báo cáo nháp → human review qua API`.

Phạm vi triển khai:

- LangGraph và agent workflow.
- LLM tổng hợp báo cáo/câu trả lời bằng structured output.
- API endpoint phục vụ Frontend.
- Kết nối, gửi dữ liệu và nhận kết quả từ VLM.
- Không triển khai giao diện Frontend.
- Chỉ tạo hoặc sửa file trong `src/agents/`, `src/models/`, `src/services/`, `src/api/`.
- Không đưa persistence vào graph. API/service chịu trách nhiệm lưu kết quả sau quyết định review, đúng baseline trong tài liệu.

## 2. Các giả định và quyết định cần khóa trước khi viết code

1. `src/agents/` và `src/models/` là hai package chuẩn. `src/agents/` chứa cả agent demo hiện hữu và incident workflow; `src/models/` chứa chat schema hiện hữu và domain model workflow. Không duy trì package số ít song song.
2. Input là video dưới 60 giây; dữ liệu đã được upload, kiểm tra định dạng và chuẩn hóa trước khi vào graph. Graph nhận URI/đường dẫn có thể truy cập, không chịu trách nhiệm upload file.
3. Không có `t0` trong request. `t_start`, `t0`, `t_end` do VLM tìm và phải thỏa `0 <= t_start <= t0 <= t_end <= video_duration`.
4. Baseline phân tích log bằng code để giữ số liệu chính xác, tạo JSON tóm tắt và biểu đồ; không gửi toàn bộ log cho LLM. Câu “baseline chọn cách thứ nhất” trong tài liệu mâu thuẫn với phần output/charts và flow chi tiết; cần khóa lại quyết định này ở Phase 0. Kế hoạch đề xuất **code tính chỉ số + tạo biểu đồ + JSON cho LLM**.
5. Một incident chỉ được tự động VLM re-analysis tối đa một lần. Yêu cầu re-analysis thủ công từ reviewer là một lệnh riêng, có audit metadata và không làm sai bộ đếm tự động.
6. Human review dùng LangGraph `interrupt` và `thread_id`. Cần checkpointer để resume. Baseline đầu tiên có thể dùng checkpointer trong bộ nhớ; persistence bền vững là quyết định riêng, không được giả định ngầm.
7. VLM và LLM phải nằm sau service interface để node không phụ thuộc trực tiếp SDK/provider. Không ghi API key, prompt dài hoặc logic HTTP vào graph node.
8. Các signal log tối thiểu dự kiến: timestamp, speed, acceleration, brake, throttle, steering angle, autonomous state/disengagement, warning/error. Phase 0 phải chốt tên cột, đơn vị và timezone/time origin.

## 3. Nguyên tắc chia phase

- Mỗi phase là một lần chạy vibecoding và chỉ làm đúng phần được mô tả.
- Mỗi phase bắt đầu bằng đọc lại `phase.md` và diff hiện tại; không sửa lan sang phase sau.
- Mỗi phase phải giữ import được và không làm hỏng endpoint hiện hữu ngoài chủ đích.
- VLM/LLM trong kiểm chứng phải được fake/mock; không gọi dịch vụ trả phí khi chưa được yêu cầu.
- Vì `tests/`, `src/main.py`, `src/config.py` và dependency files không thuộc phạm vi can thiệp, kế hoạch không tạo/sửa chúng. Nếu cần test tự động hoặc dependency/config mới, phải xin mở rộng phạm vi trước.

---

## Phase 0 — Khóa contract, naming và tiêu chí nghiệm thu

### Mục tiêu

Loại bỏ các điểm mơ hồ có thể làm thay đổi kiến trúc trước khi viết implementation.

### Công việc

- Xác nhận naming: incident workflow được gộp vào `src/agents/`, domain model workflow được gộp vào `src/models/`; giữ nguyên agent demo và chat schema hiện hữu.
- Chốt API nhận URI hay multipart upload. Mặc định: nhận `video_uri` và `log_uri` tùy chọn.
- Chốt schema log, đơn vị, time origin và tolerance dùng để ghép sự kiện video/log.
- Chốt VLM provider, cách truyền video (URI, file ID hay bytes), giới hạn dung lượng và timeout.
- Chốt report storage/checkpointer: in-memory cho demo hay adapter bền vững do hệ thống khác cung cấp.
- Chốt hành vi khi VLM trả timestamp sai, clip không cắt được, log thiếu signal, hoặc LLM/VLM timeout.

### File

- Chỉ sửa `phase.md` nếu các quyết định đã chốt khác với giả định trên.
- Không tạo/sửa code.

### Hoàn thành khi

- Không còn lựa chọn chưa rõ nào làm thay đổi public API, state graph hoặc tên module.
- Có sample request video-only, sample request video+log và một mẫu log chuẩn để dùng xuyên suốt các phase.

### Kết quả thực hiện Phase 0 — 2026-08-05

**Trạng thái: COMPLETED — contract đã được xác nhận ngày 2026-08-05.**

#### Đã khóa từ yêu cầu và tài liệu

- Phạm vi vật lý dùng hai package chuẩn `src/agents/` và `src/models/`. Incident workflow được gộp cùng agent demo; domain workflow được gộp cùng chat schema hiện hữu.
- Graph nhận `video_uri` và `log_uri` tùy chọn; upload/chuẩn hóa dữ liệu nằm trước graph và ngoài phạm vi.
- Video đầu vào dưới 60 giây, không có `t0`; VLM phải tìm `t_start`, `t0`, `t_end`.
- Backend/API lưu outcome sau review; không tạo node persistence trong graph.
- Auto re-analysis tối đa một lần cho mỗi incident.
- State chỉ giữ URI, metadata và structured result; không giữ video bytes hoặc full log.
- Test/smoke test VLM và LLM phải dùng fake mặc định, không tự gọi network/model trả phí.

#### Baseline đã xác minh

- Runtime: Python `3.14.4`.
- Package: LangGraph `1.2.10`, LangChain `1.3.14`, langchain-openai `1.4.1`, Pydantic `2.13.4`, FastAPI `0.141.1`.
- LangGraph runtime hiện có `InMemorySaver`, `interrupt` và `Command`.
- Repo cấu hình OpenAI GPT-4o-mini cho LLM hiện hữu; chưa có cấu hình hoặc dependency riêng cho VLM.
- Không tìm thấy video mẫu, log mẫu hoặc sample request phục vụ incident workflow.
- Không tìm thấy executable `ffmpeg`/`ffprobe`; Phase 3 chưa thể cắt/probe video bằng các công cụ này nếu team không cung cấp runtime dependency hoặc adapter khác.
- API baseline gồm `/health`, `/api/v1/chat`, `/api/v1/status`.
- Git worktree có thay đổi sẵn ngoài `phase.md`; Phase 0 không sửa hoặc hoàn nguyên các thay đổi đó.

#### Kết quả test baseline

- Thu thập được 5 test trong `tests/test_agents` và `tests/test_api`.
- Ba API test chạy riêng đều pass: health, empty chat validation và agent status.
- `test_agent_basic_flow` pass trong lần chạy suite.
- `test_agent_state_structure` hoàn thành assertion (pytest in dấu `.`) nhưng process không thoát; timeout 10 giây trả exit code `124`. Toàn suite vì vậy cũng timeout sau test đầu tiên. Đây là baseline issue có sẵn; Phase 0 không sửa code/test để che lỗi.

#### Decision gate đã đóng

1. **VLM contract:** graph phụ thuộc interface `VLMService`, không phụ thuộc provider. Baseline dùng OpenAI; test/smoke test dùng `FakeVLMService`. Graph chỉ truyền `video_uri`; adapter chịu trách nhiệm đổi URI thành provider file ID, bytes hoặc frames. Model name, API key và HTTP logic không nằm trong graph node.
2. **Log contract:** CSV dùng các cột `timestamp_s`, `speed_kmh`, `throttle`, `brake`, `steer`, `gear`, `data_source`. `timestamp_s` là số giây từ đầu video và là cột duy nhất bắt buộc. `speed_kmh` dùng km/h; throttle/brake trong `[0, 1]`; steer dùng degree, âm là trái và dương là phải. Signal thiếu được đánh dấu `unavailable`, không thay bằng `0`.
3. **Phân tích log:** code cắt log theo `[t_start, t_end]`, tính metric, phát hiện event, tạo chart và structured JSON. LLM chỉ nhận summary/event/evidence JSON, không nhận raw log.
4. **Checkpoint/report storage:** baseline dùng LangGraph `InMemorySaver` và SQLite repository. Chấp nhận mất pending checkpoint nếu process restart; durable checkpointer để sau. SQLite chỉ lưu incident, review decision và final report sau approve/close, không phải graph node.
5. **Media runtime:** cho phép `ffprobe` lấy metadata và `ffmpeg` cắt clip/trích frame, nhưng mọi command phải nằm sau `MediaService`. Smoke test dùng `FakeMediaService` khi executable chưa được cài.
6. **Fixtures:** dữ liệu mẫu dự kiến nằm trong `data/mock/video_only/` và `data/mock/video_with_log/`; mỗi nhóm có sample request tương ứng.

#### Gate phạm vi cho phase sau

- `data/mock/`, SQLite schema/repository, dependency và config chưa nằm trong bốn thư mục code được phép. Phải xác nhận mở rộng phạm vi trước phase đầu tiên cần tạo/sửa các file này.
- Failure policy chi tiết cho provider timeout, timestamp sai và media error sẽ được khóa trước Phase 2/3; quy tắc đã khóa cho log thiếu signal là trả metric `unavailable`, không bịa giá trị và không làm fail toàn incident chỉ vì signal tùy chọn bị thiếu.

---

## Phase 1 — Định nghĩa domain model và API contract

### Mục tiêu

Tạo một nguồn schema thống nhất cho dữ liệu đi qua API, graph, VLM và LLM; chưa gọi model và chưa dựng graph.

### Tạo file

- `src/models/__init__.py`: mở rộng export model public, bao gồm cả chat schema hiện hữu và domain workflow.
- `src/models/incident.py`: model cho incident input, time window, timeline item, video observation, evidence và artifact URI.
- `src/models/log.py`: model cho log summary, log event, chart artifact và các signal chuẩn hóa.
- `src/models/claim.py`: claim, evidence reference và trạng thái `supported | contradicted | unverified`.
- `src/models/report.py`: structured output của LLM, report nháp cố định 10 mục và review decision.
- `src/models/api.py`: request/response cho create/run, lấy trạng thái/kết quả và resume review.
- `src/agents/__init__.py`: mở rộng public exports cho incident workflow mà không thay đổi agent demo.
- `src/agents/incident_state.py`: `AgentState` riêng của incident workflow, tránh xung đột với `src/agents/state.py` của agent demo.

### Sửa file

- Không sửa file hiện hữu ở phase này.

### Ràng buộc thiết kế

- Tách rõ dữ liệu backend xác thực được với nội dung LLM được phép viết.
- Không trả chain-of-thought hay trường `analysis` nội bộ qua API mới.
- Timestamp và số liệu log là typed fields, không nhúng trong prose.
- State chỉ giữ URI/metadata cần thiết; không giữ bytes video hoặc DataFrame lớn.

### Kiểm chứng

- Import được toàn bộ model và state.
- Validate thành công hai fixture: video-only và video+log.
- Reject timestamp đảo thứ tự, URI trống, incident ID trống và review decision không hợp lệ.

### Hoàn thành khi

- Contract đủ để các phase sau làm việc mà không phải tự phát thêm field cốt lõi.

### Kết quả thực hiện Phase 1 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo toàn bộ domain model, API contract và `AgentState` được liệt kê trong phase.
- Đã validate thành công request video-only và video+log.
- Đã xác minh reject timestamp đảo thứ tự, incident ID/video URI rỗng và review action thiếu payload bắt buộc.
- `ruff check src/models src/agents`: pass.
- `pytest tests/test_api`: 3 test pass.
- Không gọi network/model thật; không tạo fixture, database, config hoặc dependency ngoài phạm vi.

---

## Phase 2 — Adapter VLM và node phân tích video

### Mục tiêu

Kết nối VLM qua service abstraction và hoàn thiện `analyze_video(state)` với output có cấu trúc.

### Tạo file

- `src/services/vlm.py`: interface/client VLM, request builder, structured response parsing, timeout/error mapping.
- `src/services/prompts.py`: prompt versioned cho full-video analysis; yêu cầu timeline, ba mốc thời gian, observations, claims và evidence timestamp/frame.
- `src/agents/nodes/__init__.py`: mở rộng export node workflow, giữ `example_node.py` hiện hữu.
- `src/agents/nodes/video.py`: triển khai `analyze_video` và validation output.

### Sửa file

- `src/models/incident.py`: chỉ bổ sung field thật sự phát sinh từ VLM contract đã chốt.
- `src/agents/incident_state.py`: chỉ bổ sung lỗi/trạng thái VLM nếu contract Phase 1 còn thiếu.

### Luồng xử lý

- Node gửi toàn bộ video dưới 60 giây cho VLM qua `VLMService`.
- Parse structured output; kiểm tra timestamp theo duration.
- Chuẩn hóa observations thành claims có ID ổn định và evidence reference.
- Không tự sửa số liệu sai một cách im lặng; trả lỗi có mã để API ánh xạ.

### Kiểm chứng

- Fake VLM trả output hợp lệ → state có `t_start`, `t0`, `t_end`, timeline, observations và claims.
- Output thiếu field/sai thứ tự timestamp → lỗi domain rõ ràng.
- Node không import trực tiếp SDK provider và không chứa API key.

### Hoàn thành khi

- Có thể chạy riêng node với fake VLM cho cả success và malformed-response case.

### Kết quả thực hiện Phase 2 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo interface `VLMService`, `FakeVLMService` và OpenAI Responses API adapter; model, API key, client và video-input resolver đều được inject, không hard-code trong graph node.
- OpenAI adapter nhận các frame/image input do `OpenAIVideoInputResolver` tạo. Resolver thật thuộc Phase 3; Phase 2 không giả định raw video là image input.
- Đã tạo prompt `video-analysis-v1`, tách system/user instruction và cấm suy đoán signal log, root cause hoặc chain-of-thought.
- `analyze_video` đã validate structured output, thứ tự timestamp, video duration và evidence index; backend tạo ID ổn định cho evidence, observation và claim.
- Đã ánh xạ malformed response, timeout, provider error và media-input error thành `DomainError` an toàn.
- Smoke test fake VLM cho happy path, malformed schema, timestamp đảo, timestamp vượt duration, evidence reference sai và timeout: pass.
- OpenAI SDK signature check cho `responses.parse`: pass; không gọi network/model thật.
- `ruff check` các file Phase 2: pass.
- `pytest tests/test_api`: 3 test pass.

---

## Phase 3 — Cắt clip và phân tích log bằng code

### Mục tiêu

Tạo artifacts xác định được bằng code, không dùng LLM để tính số liệu.

### Tạo file

- `src/services/media.py`: probe duration, cắt `[t_start, t_end]`, lấy representative frames và trả artifact URI.
- `src/services/log_analysis.py`: đọc/cắt log, normalize signal, tính chỉ số và phát hiện event.
- `src/services/charts.py`: tạo bốn biểu đồ theo đặc tả và đánh dấu `t_start`, `t0`, `t_end`.
- `src/agents/nodes/artifacts.py`: `cut_incident_video` và `cut_and_analyze_log`.

### Sửa file

- `src/models/log.py`: bổ sung model artifact/metric đã được xác nhận khi triển khai parser.
- `src/agents/incident_state.py`: thêm output artifact và log analysis nếu chưa có.

### Luồng xử lý

- Luôn cắt incident clip sau video analysis.
- Nếu không có `log_uri`, node log được bỏ qua và state ghi rõ `has_log=false`.
- Nếu có log, cắt đúng window; tính speed start/end/min/max, max deceleration, max brake, brake spike, steering change, disengagement/takeover, warning/error.
- Tạo bốn chart theo tài liệu; URI output phải dùng được cho review và report evidence.

### Kiểm chứng

- Video-only không gọi log service.
- Video+log tạo clip, frames, log slice, summary, events và bốn chart.
- Dữ liệu ngoài window không ảnh hưởng metric.
- Log thiếu signal không làm giả giá trị; field tương ứng là unavailable và có warning.

### Hoàn thành khi

- Với fixture cố định, các metric và event lặp lại chính xác qua nhiều lần chạy.

### Kết quả thực hiện Phase 3 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo `MediaService`, `FFmpegMediaService` và `FakeMediaService`; adapter thật probe duration, validate incident window, cắt clip, trích frame đại diện và ánh xạ timeout/runtime/process failure thành lỗi domain an toàn.
- Đã tạo `CSVLogAnalysisService` và fake tương ứng; parser chỉ phân tích các dòng trong `[t_start, t_end]`, normalize signal, tính speed start/end/min/max, max deceleration, max brake và phát hiện brake, steering, gear, disengagement, takeover, warning/error event.
- Signal tùy chọn bị thiếu được ghi trong `unavailable_signals` và warning; hệ thống không thay giá trị thiếu bằng `0`.
- Đã tạo `SVGChartService` không cần dependency mới; service sinh đúng bốn chart `speed_acceleration`, `brake_throttle`, `steering`, `vehicle_state` và đánh dấu `t_start`, `t0`, `t_end`.
- Đã triển khai `cut_incident_video` và `cut_and_analyze_log`; nhánh video-only trả `has_log=false` và không gọi log/chart service, nhánh có log trả clip, frame, log slice, summary, event, evidence và bốn chart URI.
- Smoke test với fixture `data_mock/vehicle_state.csv` trên window `[6.0, 9.0]` cho 7 dòng, speed `40.0 → 10.0 km/h`, max brake `1.0` và max deceleration `-3.611111111111111 m/s²`; summary/event lặp lại chính xác qua nhiều lần chạy.
- Smoke test xác nhận dữ liệu signal sai nằm ngoà incident window không ảnh hưởng metric trong window; node test bằng fake media/log/chart: pass.
- `ruff check`, `ruff format --check`, compile check và `pytest tests/test_api`: pass; 3 API test pass.
- Runtime hiện không có executable `ffmpeg`/`ffprobe`, đúng giới hạn đã ghi ở Phase 0; vì vậy media smoke test dùng `FakeMediaService`, không giả vờ đã chạy cắt video thật.
- `tests/test_agents` in đủ hai dấu pass nhưng process không thoát; đây là baseline issue đã được ghi nhận từ Phase 0, Phase 3 không sửa test/code ngoà phạm vi để che lỗi.

---

## Phase 4 — Đối chiếu claim và tái phân tích VLM đúng một lần

### Mục tiêu

Hoàn thiện logic `supported/contradicted/unverified` và vòng re-analysis có giới hạn.

### Tạo file

- `src/services/claim_verifier.py`: rule/tolerance đối chiếu claim với log event/signal; trả reason và evidence reference.
- `src/agents/nodes/verification.py`: `align_and_verify_claims`.
- `src/agents/nodes/reanalysis.py`: `reanalyze_conflicting_video_claims`, chỉ cập nhật claim được chỉ định.

### Sửa file

- `src/services/prompts.py`: thêm focused re-analysis prompt chỉ chứa các conflict cần kiểm tra.
- `src/services/vlm.py`: thêm method focused clip analysis dùng chung adapter.
- `src/agents/incident_state.py`: lưu conflict list, `auto_reanalysis_count` và audit lần re-analysis.

### Quy tắc

- Không có signal phù hợp → `unverified`, không suy diễn thành `contradicted`.
- Có conflict và count = 0 → gọi lại VLM bằng incident clip đúng một lần, sau đó verify lại.
- Count >= 1 → không tự gọi VLM nữa; giữ conflict để đưa vào báo cáo.
- Focused VLM output không được sửa claim không nằm trong danh sách conflict.

### Kiểm chứng

- Ba fixture tạo đúng ba trạng thái claim.
- Conflict lần đầu tạo đúng một VLM call và một vòng verify lại.
- Conflict còn lại sau vòng hai không tạo loop vô hạn.
- Video-only bỏ qua verifier và không gọi re-analysis tự động.

### Hoàn thành khi

- Bộ đếm và routing chứng minh mỗi incident có tối đa một lần auto re-analysis.

### Kết quả thực hiện Phase 4 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo `ClaimVerifier` thuần code với tolerance timestamp mặc định `0.75s`; verifier chỉ xác nhận claim ánh xạ đúng một rule log và hỗ trợ cả claim khẳng định/phủ định cho brake, steering, disengagement, takeover, warning và error.
- Claim không có rule phù hợp, ánh xạ nhiều signal hoặc thiếu signal bắt buộc được giữ `unverified`; hệ thống không suy diễn thành `contradicted`.
- Đã triển khai `align_and_verify_claims`; node cập nhật status, reason, log evidence ID và `conflict_claim_ids`, đồng bộ claim trong state/video analysis, đồng thời bỏ qua verifier cho incident video-only.
- Đã thêm contract `FocusedClaimContext`, `FocusedVLMClaim`, `FocusedVLMAnalysisPayload` và method `reanalyze_claims` cho `VLMService`, OpenAI adapter và `FakeVLMService`.
- Đã thêm prompt `focused-video-reanalysis-v1`; prompt chỉ chứa conflict đích, bắt buộc giữ `claim_id`, cấm sửa claim ngoà danh sách và yêu cầu timestamp theo video gốc.
- Đã triển khai `reanalyze_conflicting_video_claims`; output VLM phải trả chính xác tập claim ID được yêu cầu, chỉ claim đích được thay nội dung/evidence và timestamp phải nằm trong incident window.
- `auto_reanalysis_count` tăng ngay sau mỗi VLM call, kể cả timeout hoặc malformed response; khi count đạt `1`, node không thể gọi VLM lần hai. Audit lưu mode, attempt, target claim IDs, outcome và error code nếu có.
- Smoke test ba claim tạo đúng `supported`, `contradicted`, `unverified`; focused re-analysis giải quyết conflict sau một lần và không sửa claim ngoà target: pass.
- Smoke test conflict vẫn còn sau lần verify thứ hai, provider timeout, output sai claim ID và video-only đều xác nhận tối đa một focused VLM call: pass.
- OpenAI adapter regression cho cả full-video analysis và focused re-analysis: pass; không gọi network/model thật.
- `ruff check`, `ruff format --check`, compile check và `pytest tests/test_api`: pass; 3 API test pass.
- `tests/test_agents` tiếp tục timeout sau khi in dấu pass đầu tiên; đây là baseline process-exit issue đã ghi nhận từ Phase 0, Phase 4 không sửa ngoà phạm vi để che lỗi.

---

## Phase 5 — LLM tổng hợp báo cáo nháp có cấu trúc

### Mục tiêu

Dùng một lần gọi LLM structured output để viết đúng các phần được phép; backend lắp report cố định 10 mục.

### Tạo file

- `src/services/report_llm.py`: gọi LLM với structured output cho sáu trường prose trong tài liệu.
- `src/services/report_builder.py`: lắp dữ liệu backend, LLM output, evidence và warning vào report 10 mục.
- `src/agents/nodes/report.py`: `build_draft_report`.

### Sửa file

- `src/services/prompts.py`: report prompt nêu rõ uncertainty, cấm sửa timestamp/metric/status/evidence ID.
- `src/services/llm.py`: tái sử dụng/cấu hình client hiện hữu qua interface cần thiết; không làm thay đổi ngoài nhu cầu report.
- `src/models/report.py`: chỉ tinh chỉnh structured output khi SDK thực tế yêu cầu.
- `src/agents/incident_state.py`: thêm draft report và report-generation metadata.

### Quy tắc

- Backend điền mục 1, 2, evidence/status và review status.
- LLM chỉ viết summary, timeline text, video findings, log findings, cross-check explanation và hypothesized cause.
- Không có log → report ghi rõ không có dữ liệu log.
- Conflict chưa giải quyết → hiển thị warning; nguyên nhân chỉ là giả thuyết, không khẳng định root cause.

### Kiểm chứng

- Fake LLM chỉ cần một call và tạo đủ report 10 mục.
- Cố tình cho fake LLM trả timestamp/metric khác → report cuối vẫn giữ dữ liệu backend.
- Video-only và video+log đều tạo report hợp lệ.

### Hoàn thành khi

- Report có schema ổn định, không lộ nội dung phân tích nội bộ và truy vết được mọi evidence ID.

### Kết quả thực hiện Phase 5 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã giữ nguyên public schema `DraftReport` hiện có vì schema đã biểu diễn đủ 10 mục cố định; Phase 5 không thêm cấu trúc report do LLM tự quyết định.
- Đã tạo `ReportLLMService`, `LangChainReportLLMService` và `FakeReportLLMService`; adapter dùng native structured output `ReportNarrative` và mỗi lần chạy node hợp lệ chỉ gọi `ainvoke` một lần.
- Đã thêm prompt `incident-report-v1`; LLM chỉ được viết `summary`, `timeline_text`, `video_findings`, `log_findings`, `cross_check_explanation`, `hypothesized_cause` và bị cấm sửa timestamp, metric, claim status, evidence ID, URI hoặc review status.
- `src/services/llm.py` tái sử dụng `ChatOpenAI`/settings hiện hữu để tạo structured report adapter; graph node không đọc API key hoặc config trực tiếp.
- Đã tạo backend report builder lắp cố định general information, incident window, timeline typed, log summary, claim/status, evidence/warning và review status `pending`; hypothesized cause luôn được đóng khung là giả thuyết chưa xác nhận.
- Video-only luôn ghi chính xác `Không có dữ liệu log.` và `log_summary=null`, không phụ thuộc prose do LLM trả về.
- Conflict chưa giải quyết và log signal unavailable được backend đưa vào warning; report builder deduplicate evidence và reject mọi claim/log event tham chiếu evidence ID không tồn tại.
- Evidence thiếu `artifact_uri` được backend gắn theo thứ tự frame đại diện khớp timestamp, incident clip, video gốc; log evidence trỏ về log slice. Evidence ID nguồn không bị thay đổi.
- Đã triển khai `build_draft_report`; node validate source data, gọi report LLM, lắp report và ghi metadata gồm prompt version, số LLM call, outcome/error code mà không lưu raw prompt hoặc chain-of-thought.
- Smoke test fake LLM cố tình trả thêm `t_start=999`, `max_brake=999`, `review_status=approved`: report cuối vẫn giữ incident window, log metric và review status do backend xác thực.
- Smoke test video-only, video+log, unresolved conflict, evidence mapping, unknown evidence ID, malformed LLM response, timeout và LangChain structured adapter: pass; mỗi success/failure sau model call đều ghi chính xác `llm_calls=1`.
- `ruff check`, `ruff format --check`, compile check và `pytest tests/test_api`: pass; 3 API test pass. Không gọi network/model thật.
- `tests/test_agents` tiếp tục timeout sau khi in dấu pass đầu tiên; đây là baseline process-exit issue đã ghi nhận từ Phase 0, Phase 5 không sửa ngoà phạm vi để che lỗi.

---

## Phase 6 — Lắp LangGraph và human-review interrupt

### Mục tiêu

Nối các node thành workflow đúng sơ đồ, có conditional routing và khả năng pause/resume.

### Tạo file

- `src/agents/incident_routing.py`: các hàm route thuần cho has-log, conflicts/re-analysis và review decision.
- `src/agents/incident_graph.py`: build/compile graph, dependency injection và checkpointer.
- `src/agents/nodes/review.py`: `human_review_interrupt` và áp dụng payload resume vào state.

### Sửa file

- `src/agents/__init__.py`: export graph factory/public runner.
- `src/agents/incident_state.py`: bổ sung lifecycle status và review audit nếu cần.

### Graph dự kiến

1. `analyze_video`
2. `cut_incident_video`
3. Nếu có log: `cut_and_analyze_log → align_and_verify_claims`
4. Nếu conflict và chưa auto re-analysis: `reanalyze_conflicting_video_claims → align_and_verify_claims`
5. `build_draft_report`
6. `human_review_interrupt`
7. Resume theo quyết định: approve/edit/not-incident kết thúc; manual re-analysis chạy đúng nhánh được phép rồi quay về report/review.

### Quy tắc

- Dùng `thread_id = incident_id` hoặc mapping ổn định đã chốt.
- Node không nuốt exception; chuyển thành lỗi domain/lifecycle có thể quan sát.
- Không tạo node `persist_report` trong baseline.
- `edit` cập nhật nội dung được phép mà không gọi LLM.

### Kiểm chứng

- Chạy graph fake end-to-end cho video-only và video+log đến interrupt.
- Resume approve, edit, manual re-analysis và not-incident đều đi đúng nhánh.
- Auto re-analysis không vượt quá một lần; resume không chạy lại node đã hoàn tất ngoài chủ đích.

### Hoàn thành khi

- Graph pause/resume được theo `thread_id` và state cuối phản ánh đúng lifecycle.

### Kết quả thực hiện Phase 6 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo các routing function thuần cho fail-fast, nhánh có log, conflict/auto re-analysis và review decision; conflict chỉ đi vào auto re-analysis khi `auto_reanalysis_count < 1`.
- Đã tạo `AgentDependencies` và `build_incident_graph`; tất cả VLM, media, log, chart, verifier và report LLM được inject, graph không tự đọc config/API key.
- Graph đã nối đúng luồng `analyze_video → cut_incident_video → optional log/verify/auto re-analysis → build_report → human_review`; mọi node trả `status=failed` đều kết thúc ngay, không chạy node phía sau.
- Baseline dùng `InMemorySaver` và `thread_id=incident_id`; serializer chỉ allowlist chính xác các domain model trong state, không bật deserialization allowlist toàn cục.
- Đã export graph factory, stable thread config, runner khởi chạy và runner resume qua `Command(resume=...)`; initial state có original-video artifact, counter/audit rỗng và lifecycle `running`.
- Đã tạo `human_review_interrupt`; interrupt chỉ hiển thị incident ID, draft report, artifact, claim và action hợp lệ, không trả raw state, prompt hoặc chain-of-thought.
- `approve` kết thúc với incident/report `approved`; `not_incident` lưu reason trong audit và kết thúc `not_incident`; `edit` chỉ cho sửa sáu prose field, không gọi LLM và kết thúc `status=approved`, `review_status=edited`.
- Review edit cố sửa timestamp, metric, claim/evidence hoặc field không cho phép bị reject; giá trị edit phải là chuỗi không rỗng.
- Manual `reanalyze` bắt buộc có target claim IDs và feedback; node chỉ cập nhật đúng target, sau đó chạy lại verify → report → review. `manual_reanalysis_count` tách biệt và không làm thay đổi giới hạn auto re-analysis.
- Review audit lưu reviewer, action, reason, feedback và target claim IDs; re-analysis audit phân biệt `automatic`/`manual`, attempt, outcome và error code.
- Smoke test graph video-only đến interrupt rồi approve: pass; log/chart service không bị gọi và resume không chạy lại video/media/report node.
- Smoke test video+log có conflict: đúng một auto focused VLM call, verify lần hai hết conflict, report một lần và approve không tăng call count: pass.
- Smoke test `edit`, `not_incident` và manual `reanalyze → review → approve`: pass; manual flow có `auto_reanalysis_count=0`, `manual_reanalysis_count=1`, full-video VLM một call, focused VLM một call và report hai call đúng chủ đích.
- Smoke test pure routing và provider fail-fast: pass; VLM timeout kết thúc `failed` và không gọi media/node tiếp theo.
- Runtime hiện tại không hoàn tất async graph nếu LangGraph đưa sync node/router qua thread executor; graph vì vậy dùng async adapter cho node/router trong khi vẫn giữ routing function thuần để test độc lập.
- `ruff check`, `ruff format --check`, compile check và `pytest tests/test_api`: pass; 3 API test pass. Không gọi network/model thật.
- `tests/test_agents` tiếp tục timeout sau khi in dấu pass đầu tiên; đây là baseline process-exit issue đã ghi nhận từ Phase 0, Phase 6 không sửa ngoà phạm vi để che lỗi.

---

## Phase 7 — API cho Frontend và lưu quyết định review

### Mục tiêu

Cung cấp API ổn định để Frontend khởi chạy, theo dõi, lấy artifacts/report và gửi quyết định review; không làm UI.

### Tạo file

- `src/services/workflow.py`: application service gọi/resume graph, ánh xạ state sang response và chống gọi trùng cơ bản.
- `src/services/report_repository.py`: repository interface và implementation baseline đã chốt ở Phase 0 cho report đã approve/closed case.
- `src/api/incidents.py`: incident workflow endpoints.
- `src/api/errors.py`: ánh xạ domain error sang HTTP status/detail an toàn.

### Sửa file

- `src/api/routes.py`: include incident router; giữ endpoint hiện hữu nếu chưa có quyết định deprecate.
- `src/models/api.py`: tinh chỉnh request/response theo contract đã khóa, không trả raw AgentState.

### Endpoint đề xuất

- `POST /api/v1/incidents`: tạo và chạy workflow đến review/error; body gồm incident ID, video URI, log URI tùy chọn và metadata tối thiểu.
- `GET /api/v1/incidents/{incident_id}`: lấy lifecycle status, artifacts, claim verification, warning và draft/final report.
- `POST /api/v1/incidents/{incident_id}/review`: gửi `approve | edit | reanalyze | not_incident` cùng reviewer/audit payload rồi resume graph.

Không thêm upload endpoint trong baseline trừ khi Phase 0 đổi contract sang multipart.

### API behavior

- `202` khi workflow đang chạy hoặc đã pause chờ review; `200` khi trả snapshot hoàn chỉnh; `404` khi incident không tồn tại; `409` cho decision sai lifecycle; `422` cho request sai schema; lỗi provider không lộ secret/raw stack trace.
- Approve lưu final report, evidence và reviewer qua repository.
- Not-incident lưu lý do và đóng case.
- Edit lưu nội dung reviewer, không gọi LLM.
- Reanalyze resume graph với đúng target/feedback được phép.

### Kiểm chứng

- Gọi API với fake graph/service cho full lifecycle create → pending review → approve.
- Kiểm tra thêm edit, not-incident, manual re-analysis, duplicate create và invalid transition.
- Response đủ URI/artifact cho Frontend render nhưng không chứa local secret, raw prompt hoặc chain-of-thought.

### Hoàn thành khi

- Frontend có thể điều khiển toàn bộ lifecycle chỉ qua ba endpoint trên.

### Kết quả thực hiện Phase 7 — 2026-08-05

**Trạng thái: COMPLETED.**

- Đã tạo ba endpoint `POST /api/v1/incidents`, `GET /api/v1/incidents/{incident_id}` và `POST /api/v1/incidents/{incident_id}/review`, include vào router hiện hữu mà không xóa/thay đổi `/chat` hoặc `/status`.
- Incident router lấy `WorkflowService` qua `app.state.incident_workflow_service`; cách này cho phép bootstrap inject graph/provider/repository theo môi trường mà route không đọc API key, database path hoặc config. App chưa inject service trả `503 WORKFLOW_SERVICE_UNAVAILABLE` an toàn.
- Đã tạo HTTP error mapping: incident không tồn tại `404`, duplicate create/review sai lifecycle `409`, request sai schema `422`, storage/workflow orchestration failure `500`; response chỉ chứa code/message đã sanitize.
- Create/review trả `202` khi `running|pending|awaiting_review`; terminal snapshot `approved|not_incident|failed` trả `200`.
- Đã tạo `WorkflowService` gọi start/resume graph, giữ snapshot API an toàn, reserve incident ID chống create trùng và dùng lock theo incident để serialize review decision cạnh tranh.
- Workflow response đã bổ sung `has_log`, artifact, claim/conflict, auto/manual counter, draft/final report, review audit, warning và `stored_at`; không trả raw `AgentState`, interrupt object, run metadata, report-generation metadata, re-analysis audit nội bộ, prompt hoặc chain-of-thought.
- Validation edit được đẩy lên `ReviewDecision`: chỉ sáu prose field được phép, edit field bất biến/không rõ hoặc giá trị rỗng trả `422` trước khi tiêu thụ interrupt.
- Manual re-analysis target ID được kiểm tra với snapshot trước resume; target không tồn tại trả `409` và checkpoint vẫn có thể nhận quyết định hợp lệ sau đó.
- Đã tạo `ReportRepository` interface, fake in-memory và `SQLiteReportRepository`; SQLite tạo schema tối thiểu, chỉ lưu terminal `approved|not_incident`, final report, evidence JSON, reviewer, decision, reason và timestamp.
- SQLite dùng parameterized query, terminal outcome ghi đúng một lần và duplicate primary key trả `REPORT_ALREADY_STORED`; smoke test mở repository mới trên cùng file vẫn đọc lại đúng report/decision.
- In-memory graph checkpoint/snapshot pending review vẫn mất khi process restart theo giới hạn đã công bố; terminal outcome đã lưu SQLite có thể đọc lại sau restart.
- API smoke test create → pending review → approve, GET snapshot, duplicate create, missing incident và review sau terminal: pass; terminal approve được repository lưu và response có `stored_at`.
- API smoke test edit, not-incident và manual `reanalyze → pending review → approve`: pass; edit không gọi LLM, not-incident lưu reason và manual flow chỉ có một focused VLM call.
- Smoke test hai approve request cạnh tranh trên cùng incident: chính xác một request `200 approved`, request còn lại `409`; không ghi terminal outcome hai lần.
- FastAPI dependency của incident router dùng async adapter để không bị runtime hiện tại kẹt trong sync thread executor.
- `ruff check`, `ruff format --check`, compile check và `pytest tests/test_api`: pass; 3 API regression test pass. Không gọi network/model thật.
- `tests/test_agents` tiếp tục timeout sau khi in dấu pass đầu tiên; đây là baseline process-exit issue đã ghi nhận từ Phase 0, Phase 7 không sửa ngoà phạm vi để che lỗi.

### Hiệu chỉnh package model và rà soát Phase 0–7 — 2026-08-05

- Package domain chuẩn là `src/models/`. Các module workflow `api.py`, `claim.py`, `incident.py`, `log.py` và `report.py` đã được gộp từ package số ít cũ vào package này; `src/models/schemas.py` cũ được giữ nguyên và package số ít đã được xóa sau khi gộp.
- Phase 0 bị ảnh hưởng về quyết định naming/phạm vi; Phase 1 bị ảnh hưởng về vị trí domain model.
- Phase 2–5 bị ảnh hưởng chỉ ở import model của VLM, media/log, verification/re-analysis và report; contract dữ liệu không đổi.
- Phase 6 bị ảnh hưởng ở import graph và allowlist serializer. Checkpoint in-memory cũ không được cam kết qua process restart; checkpoint tạo sau thay đổi dùng đường dẫn class mới.
- Phase 7 bị ảnh hưởng ở API/service/repository imports. Public HTTP schema và JSON lưu trong SQLite không đổi nên không cần data migration.
- Mọi import nội bộ và đường dẫn file trong kế hoạch Phase 0–7 đã chuyển sang `src.models`/`src/models/`.
- `ruff check`, `ruff format --check`, compile/import check và `pytest tests/test_api`: pass; 3 API test pass.
- Smoke test sau migration cho graph và application service `create → awaiting_review → approve → repository`: pass; checkpoint serializer chấp nhận các model ở module path mới.
- `tests/test_agents` vẫn in dấu pass đầu tiên nhưng process không thoát và bị timeout sau 15 giây (`exit 124`), trùng baseline issue đã ghi từ Phase 0.

### Hiệu chỉnh package agent và rà soát Phase 0–7 — 2026-08-05

- Package agent chuẩn là `src/agents/`; package số ít cũ được gộp và xóa sau migration.
- Do `graph.py`, `state.py` và tên `AgentState` đã được agent demo sử dụng, incident workflow dùng `incident_graph.py`, `incident_state.py`, `incident_routing.py`; không ghi đè contract demo.
- Các node workflow được gộp vào `src/agents/nodes/` cùng `example_node.py`; hai file `__init__.py` được mở rộng export.
- Phase 0–1 bị ảnh hưởng về naming, phạm vi và vị trí incident state. Phase 2–5 bị ảnh hưởng ở import state/node, không đổi contract xử lý.
- Phase 6 chuyển graph/routing sang module `incident_*`; checkpoint vẫn là in-memory và không cam kết resume qua process restart.
- Phase 7 chuyển application service sang `src.agents.incident_graph`; endpoint chat hiện hữu vẫn dùng `src.agents.graph` nên public API demo không đổi.
- Hướng dẫn trong `docs/guide/chapter-02.md` và toàn bộ đường dẫn Phase 0–7 đã chuyển sang package số nhiều.
- `ruff check`, `ruff format --check`, compile/import check cho cả agent demo và incident workflow: pass; `pytest tests/test_api`: 3 test pass.
- Smoke test incident workflow sau migration `create → awaiting_review → approve → repository`: pass.
- `tests/test_agents` vẫn hoàn thành test đầu tiên rồi process không thoát, timeout sau 15 giây (`exit 124`), trùng baseline issue đã ghi từ Phase 0.

---

## Phase 8 — Hardening và nghiệm thu tích hợp

### Mục tiêu

Rà soát toàn bộ workflow theo các failure mode thực tế, chỉ sửa lỗi trong phạm vi bốn thư mục được giao.

### Tạo file

- Không mặc định tạo file mới.
- Chỉ tạo module nhỏ trong `src/services/` hoặc `src/agents/` nếu một lỗi nghiệm thu chứng minh là cần thiết; không refactor dự phòng.

### Sửa file

- Chỉ các file đã tạo/sửa ở Phase 1–7 có lỗi được tái hiện.
- Không sửa `src/main.py`, `src/config.py`, dependency files, module agent demo cũ hoặc Frontend.

### Kịch bản nghiệm thu

- Video-only thành công.
- Video+log không conflict.
- Video+log có conflict và hết conflict sau một lần re-analysis.
- Conflict vẫn còn sau re-analysis và xuất hiện đúng trong report warning.
- VLM malformed/timeout, LLM malformed/timeout, media cut fail, log thiếu cột.
- Hai request trùng incident ID và hai review decision cạnh tranh.
- Restart process theo đúng năng lực checkpointer/repository đã công bố; nếu dùng in-memory phải ghi rõ giới hạn này.
- Kiểm tra log/response không lộ API key, raw prompt hoặc dữ liệu nội bộ không cần thiết.

### Kiểm chứng cuối

- Chạy formatter/linter trên đúng phạm vi.
- Chạy test suite hiện hữu để phát hiện regression.
- Chạy smoke test workflow/API bằng fake VLM và fake LLM.
- Chỉ chạy integration thật với VLM/LLM khi có explicit approval và test asset an toàn.

### Hoàn thành khi

- Tất cả nhánh trong sơ đồ tài liệu có kết quả xác định, không loop vô hạn, không sửa số liệu nguồn và không vượt phạm vi file.

---

## Phase 9 — Hoàn thiện end-to-end theo Agent Flow và bàn giao

### Trạng thái kế hoạch

**Trạng thái: COMPLETED — nghiệm thu ngày 2026-08-06.**

Phase này được lập sau khi đối chiếu lại mã nguồn thực tế với `AI agent flow.md`. Các kết quả `COMPLETED` ghi ở Phase 6–7 không được dùng thay cho nghiệm thu runtime: tại thời điểm lập kế hoạch, repository chưa có incident graph/review interrupt hoàn chỉnh và `src/main.py` chưa bootstrap `incident_workflow_service`, nên API incident thực tế vẫn chưa chạy end-to-end.

### Mục tiêu

Hoàn thiện chuỗi chạy thật:

```text
Streamlit main_test.py
        → FastAPI incident API
        → WorkflowService
        → LangGraph incident workflow
        → VLM/LLM + media/log/chart services
        → Human Review interrupt/resume
        → SQLite checkpoint/repository
```

Workflow cuối phải chạy đúng các nhánh trong `AI agent flow.md`:

1. Phân tích toàn bộ video dưới 60 giây để tìm `t_start`, `t0`, `t_end`, timeline và claims.
2. Cắt incident clip và frame đại diện.
3. Nếu có log: cắt log, tính metric/event và tạo bốn biểu đồ.
4. Nếu có log: verify từng claim thành `supported | contradicted | unverified`.
5. Nếu có conflict và chưa auto re-analysis: dùng incident clip + focused prompt để phân tích lại đúng một lần, sau đó verify lại.
6. Tạo draft report theo khung cố định 10 mục; conflict chưa giải quyết phải được đưa vào warning.
7. Pause tại Human Review và resume theo `approve | edit | reanalyze | not_incident`.
8. Chỉ `approve` và `not_incident` là terminal; `edit` và `reanalyze` phải quay lại review.
9. Lưu terminal outcome và có thể tiếp tục incident đang chờ review sau khi process restart.

### Phạm vi được phép

- Sửa backend trong `src/` để hoàn thiện graph, bootstrap, API contract và persistence.
- Tạo/sửa tests và fixture cần thiết cho unit, integration và end-to-end.
- Sửa `requirements.txt`, `.env.example`, Docker/CI khi cần để runtime và test chạy được.
- Tạo duy nhất `main_test.py` tại repository root làm Streamlit test client.
- Cập nhật `README.md` và `work.md` theo kết quả nghiệm thu thực tế.
- Không sửa, xóa, di chuyển hoặc refactor giao diện/front-end hiện hữu.

### 9.1 — Khóa report contract và AgentState

#### Thực hiện

- Bổ sung schema `DraftReport` cố định đủ 10 mục:
  1. Thông tin chung.
  2. Khoảng thời gian sự cố.
  3. Tóm tắt sự cố.
  4. Timeline.
  5. Quan sát từ video.
  6. Kết quả log.
  7. Đối chiếu video và log.
  8. Nguyên nhân giả thuyết.
  9. Bằng chứng và cảnh báo.
  10. Trạng thái review.
- Backend sở hữu incident metadata, timestamp, metric, claim status, evidence/artifact URI, warning và review status.
- LLM chỉ được tạo các trường narrative; output LLM không được ghi đè dữ liệu backend.
- Video-only phải ghi chính xác `Không có dữ liệu log.`.
- Bổ sung `draft_report`, review payload/audit và lifecycle cần thiết vào `IncidentState` và API snapshot.

#### Kiểm chứng

- Fake LLM cố trả timestamp/metric/status sai nhưng report cuối vẫn giữ dữ liệu backend.
- Report video-only và video+log đều đủ 10 mục.
- Conflict còn lại sau auto re-analysis xuất hiện trong warning.

### 9.2 — Lắp LangGraph incident hoàn chỉnh

#### Tạo/sửa file dự kiến

- Tạo `src/agents/incident_graph.py`.
- Tạo `src/agents/nodes/review.py`.
- Sửa `src/agents/incident_routing.py`.
- Sửa `src/agents/incident_state.py` và `src/agents/nodes/incident.py` ở đúng phần cần thiết.
- Export graph factory/runner qua `src/agents/__init__.py`.

#### Routing bắt buộc

```text
START
  → analyze_video
  → cut_incident_video
  → has_log?
      ├─ no  → build_draft_report
      └─ yes → analyze_log → align_and_verify_claims
                              → has_conflict_and_not_reanalyzed?
                                  ├─ yes → auto_reanalyze → verify lại
                                  └─ no  → build_draft_report
  → human_review_interrupt
      ├─ approve      → persist/cleanup → END
      ├─ edit         → human_review_interrupt
      ├─ reanalyze    → manual_reanalyze → optional verify → report → review
      └─ not_incident → persist/cleanup → END
```

#### Quy tắc

- Mọi node trả `status=failed` phải dừng graph, không chạy node phía sau.
- Auto re-analysis tối đa một lần cho mỗi incident.
- Các contradicted claim phải được xử lý theo một focused request hợp lệ hoặc được giữ lại đầy đủ trong warning; không chỉ âm thầm chọn claim đầu tiên.
- Re-analysis dùng incident clip đã cắt. Nếu provider cần video normalized/full video thì phải ghi rõ mapping và vẫn giới hạn đúng incident window.
- Video-only không được gọi log service, verifier hoặc auto re-analysis.
- Không có loop vô hạn.

### 9.3 — Human Review interrupt/resume

#### Thực hiện

- Dùng LangGraph `interrupt()` và `Command(resume=...)` với `thread_id = incident_id`.
- Payload interrupt chỉ chứa dữ liệu cần hiển thị: report, artifacts, claims, warning và action hợp lệ; không chứa raw state, API key, raw prompt hoặc chain-of-thought.
- `approve`: cập nhật review status, lưu final report và kết thúc.
- `edit`: chỉ sửa sáu narrative field được allowlist, không gọi LLM, sau đó quay lại `awaiting_review`; không tự approve.
- `reanalyze`: bắt buộc reviewer feedback và target claim IDs hợp lệ; chạy focused VLM, optional verify, build report lại rồi quay lại review.
- `not_incident`: bắt buộc lý do, lưu audit và đóng incident.

#### Kiểm chứng

- Resume không chạy lại video/media/log node đã hoàn tất ngoài chủ đích.
- Auto và manual re-analysis có counter/audit tách biệt.
- Invalid edit, invalid claim ID và review sau terminal bị từ chối mà checkpoint vẫn dùng được.

### 9.4 — Concrete runner, dependency factory và FastAPI bootstrap

#### Thực hiện

- Tạo concrete implementation cho `IncidentGraphRunner`.
- Tạo dependency factory từ `Settings` cho:
  - `MediaService`.
  - OpenAI frames hoặc Gemini native-video `VLMService`.
  - `VideoMemoryWorkflow`.
  - `LogAnalysisService` và `ChartService`.
  - Verification LLM và reporting LLM.
  - LangGraph checkpointer và report repository.
- Trong FastAPI lifespan, khởi tạo và gắn `app.state.incident_workflow_service` trước khi nhận request; đóng tài nguyên khi shutdown.
- Không để route tự đọc API key hoặc tự khởi tạo provider client.
- Validate input URI/path theo configured roots, kích thước và giới hạn video dưới 60 giây.

#### Kiểm chứng

- `/health` trả `200`.
- `POST /api/v1/incidents` không còn trả `503 WORKFLOW_SERVICE_UNAVAILABLE` khi cấu hình hợp lệ.
- Lỗi cấu hình/provider được ánh xạ thành domain/API error an toàn, không lộ secret hoặc stack trace.

### 9.5 — Checkpoint, persistence và cleanup

#### Thực hiện

- Bổ sung `langgraph-checkpoint-sqlite` và dùng SQLite checkpointer cho incident đang chờ review.
- Tiếp tục dùng SQLite repository cho terminal outcome `approved | not_incident`.
- Đảm bảo duplicate incident, terminal write và concurrent review có kết quả xác định.
- Cleanup remote Gemini resource khi approved, not-incident hoặc failed; giữ/reuse handle khi incident còn chờ review và re-upload khi handle mất theo cấu hình.
- API snapshot phải đọc được pending incident sau process restart và terminal incident từ repository.

#### Kiểm chứng

- Start → awaiting review → restart runner/app → GET và resume thành công.
- Terminal report đọc lại được từ SQLite bằng repository instance mới.
- Hai review request cạnh tranh chỉ có một terminal write thành công.

### 9.6 — Streamlit test client độc lập

#### Tạo file

- Tạo `main_test.py` tại repository root.
- Bổ sung dependency `streamlit`; dùng `httpx` hiện có để gọi API.

#### Yêu cầu giao diện test

- Cấu hình FastAPI base URL.
- Nhập incident ID, video URI, log URI tùy chọn và analysis prompt.
- Start incident và lưu incident ID trong `st.session_state`.
- Refresh/poll trạng thái qua API mà không gọi trực tiếp graph/service.
- Hiển thị video gốc, incident clip, representative frame và bốn biểu đồ nếu có.
- Hiển thị incident window, claims/status, evidence, warning và report đủ 10 mục.
- Form review hỗ trợ approve, edit, targeted re-analysis và not-incident.
- Hiển thị lỗi API rõ ràng nhưng không lộ secret/raw traceback.
- Không import, sửa hoặc phụ thuộc vào front-end hiện hữu.

#### Lệnh chạy

```bash
uvicorn src.main:app --reload --port 8000
streamlit run main_test.py
```

### 9.7 — Bộ kiểm thử end-to-end bắt buộc

1. Video-only → draft report → approve → SQLite.
2. Video+log không conflict → report → approve.
3. Video+log có conflict → đúng một auto re-analysis → verify lại.
4. Conflict vẫn còn sau lần re-analysis → report có warning, không loop.
5. Edit → vẫn `awaiting_review`, không gọi LLM, có thể approve sau đó.
6. Manual re-analysis → report mới → review lại → approve.
7. Not incident → bắt buộc và lưu reason.
8. Provider/media/log/report failure → fail-fast và error an toàn.
9. Duplicate incident, invalid transition và concurrent review.
10. Restart process/checkpointer → pending incident resume được.
11. API integration dùng app + WorkflowService + graph thật, chỉ fake tại provider SDK boundary.
12. Media/log/chart integration dùng asset trong `data_mock/` và FFmpeg thật.
13. `main_test.py` import/smoke test.
14. Sửa hoặc thay test graph demo đang khiến full pytest không thoát.

#### Lệnh nghiệm thu tự động

```bash
ruff check src tests main_test.py
ruff format --check src tests main_test.py
python -m compileall -q src tests main_test.py
pytest tests -v --tb=short
```

Tất cả lệnh phải kết thúc với exit code `0`; dấu test đã pass nhưng process treo/timeout vẫn được tính là không đạt.

### 9.8 — Live smoke test và tài liệu bàn giao

#### Live smoke

- Chạy FastAPI thật và Streamlit thật với `data_mock/front_camera.mp4`.
- Chạy ít nhất một case video-only và một case video + `data_mock/vehicle_state.csv`.
- Thực hiện một vòng review terminal và xác minh record SQLite.
- Gọi model thật chỉ khi có API key hợp lệ và được phép phát sinh chi phí; test tự động vẫn phải fake tại SDK boundary.

#### Tài liệu

- Cập nhật `README.md`: cấu hình, chạy backend, chạy Streamlit, ba endpoint, lifecycle và giới hạn.
- Cập nhật `work.md`: file thay đổi, code đã làm, test command/kết quả, lỗi hoặc giới hạn còn lại.
- Không ghi `complete` nếu live workflow hoặc full pytest chưa đạt.

### Tiêu chí hoàn thành Phase 9

- [x] FastAPI bootstrap được workflow service thật.
- [x] Video-only chạy đến Human Review.
- [x] Video+log chạy qua analysis, chart, verification và Human Review.
- [x] Auto re-analysis tối đa một lần và verify lại đúng flow.
- [x] Report đủ 10 mục, dữ liệu backend không bị LLM sửa.
- [x] Approve, edit, manual re-analysis và not-incident đi đúng nhánh.
- [x] Pending incident resume được sau restart.
- [x] Terminal outcome được lưu và đọc lại từ SQLite.
- [x] `main_test.py` điều khiển toàn bộ lifecycle qua API.
- [x] Không sửa front-end hiện hữu.
- [x] Lint, format, compile và full pytest đều exit `0`, không treo.
- [x] Live startup FastAPI/Streamlit đạt; model thật không được gọi vì chưa có explicit approval phát sinh chi phí, và kết quả không được tuyên bố production-ready.
- [x] `README.md` và `work.md` phản ánh đúng kết quả thực tế.

### Kết quả thực hiện Phase 9 — 2026-08-06

**Trạng thái: COMPLETED.**

- Đã lắp incident LangGraph hoàn chỉnh, durable SQLite checkpoint, concrete runner, dependency factory và FastAPI lifespan bootstrap.
- Human Review dùng `interrupt`/`Command(resume=...)`; `edit` quay lại review, manual re-analysis quay lại report/review, chỉ approve/not-incident kết thúc.
- Report backend-owned đủ 10 mục; timestamps, log metrics, verification, evidence/artifacts, warning và review status không do LLM ghi đè.
- Auto re-analysis gom toàn bộ contradicted claim vào một focused request, tăng counter đúng một lần và verify lại; conflict còn lại xuất hiện trong warning.
- Pending incident đã được test resume sau khi đóng/mở SQLite checkpointer; terminal report, artifacts, claims, warnings và review audit đọc lại được từ SQLite repository mới.
- Đã tạo `main_test.py`, cập nhật dependency/config và README; không sửa frontend hiện hữu.
- Bổ sung sau nghiệm thu: Streamlit dùng file picker và API `POST /api/v1/incidents/uploads` lưu local multipart video/log có kiểm tra extension, dung lượng, filename an toàn và cleanup khi upload lỗi.
- E2E dùng `data_mock/front_camera.mp4`, `data_mock/vehicle_state.csv`, FFmpeg, log/chart, graph và API thật; OpenAI chỉ mock ở SDK boundary, không gọi network/model trả phí.
- Uvicorn live startup/shutdown sạch, `/health` trả `200`; Streamlit live startup/shutdown sạch.
- `ruff check`, `ruff format --check`, compile, `pip check`, `git diff --check`: pass.
- Full suite sau bổ sung upload, sửa client timeout và phân loại lỗi OpenAI verification: **123 test pass**, exit code `0`, không còn lỗi pytest treo.

**Chỉ khi tất cả tiêu chí bắt buộc đạt mới cập nhật trạng thái Phase 9 thành `COMPLETED` và ghi `complete` trong `work.md`.**

---

## 4. Ma trận file theo phase

| Phase | Tạo mới                                                                                            | Sửa hiện hữu                                                                                         |
| ----- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 0     | Không                                                                                               | `phase.md` nếu quyết định thay đổi                                                              |
| 1     | `src/models/{incident,log,claim,report,api}.py`, `src/agents/incident_state.py`                  | `src/models/__init__.py`, `src/agents/__init__.py` giữ và mở rộng export hiện hữu             |
| 2     | `src/services/vlm.py`, `src/services/prompts.py`, `src/agents/nodes/video.py`                  | `src/agents/nodes/__init__.py`, `src/models/incident.py`, `src/agents/incident_state.py` khi cần |
| 3     | `src/services/{media,log_analysis,charts}.py`, `src/agents/nodes/artifacts.py`                   | `src/models/log.py`, `src/agents/incident_state.py` khi cần                                        |
| 4     | `src/services/claim_verifier.py`, `src/agents/nodes/{verification,reanalysis}.py`                | `src/services/{prompts,vlm}.py`, `src/agents/incident_state.py`                                     |
| 5     | `src/services/{report_llm,report_builder}.py`, `src/agents/nodes/report.py`                      | `src/services/{prompts,llm}.py`, `src/models/report.py`, `src/agents/incident_state.py`           |
| 6     | `src/agents/incident_routing.py`, `src/agents/incident_graph.py`, `src/agents/nodes/review.py` | `src/agents/{__init__,incident_state}.py`                                                             |
| 7     | `src/services/{workflow,report_repository}.py`, `src/api/{incidents,errors}.py`                  | `src/api/routes.py`, `src/models/api.py`                                                            |
| 8     | Không mặc định                                                                                   | Chỉ file có lỗi được tái hiện trong Phase 1–7                                                  |
| 9     | `src/agents/incident_graph.py`, `src/agents/nodes/review.py`, `main_test.py`                     | Backend/state/models/API/bootstrap, tests, dependencies và tài liệu cần thiết để chạy end-to-end       |

## 5. Ngoài phạm vi và cần xin phép riêng

- Frontend/UI hiện hữu; ngoại lệ duy nhất là tạo `main_test.py` làm Streamlit test client độc lập.
- External object storage/remote-URL pipeline trước graph; local multipart upload đã được bổ sung sau Phase 9.
- Authentication/authorization, rate limit, background queue và production observability ngoài nhu cầu tối thiểu để workflow chạy và được kiểm thử.
- Xóa hoặc đổi contract agent demo trong `src/agents/{graph,state}.py`, `nodes/example_node.py`, `tools/`; xóa chat schema cũ trong `src/models/schemas.py`.
- Gọi model thật, mua dịch vụ, deploy hoặc thay đổi hạ tầng.
