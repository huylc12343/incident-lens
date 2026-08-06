# Work report — Phase 0

## Trạng thái

`complete`

Phase 0 — Contract và provider matrix đã hoàn tất theo phạm vi được mô tả trong `phase.md`. Phase này chỉ khóa quyết định kiến trúc và không yêu cầu sửa mã nguồn.

## Tài liệu đã đọc

- `phase.md`: kiến trúc kỹ thuật và lộ trình 10 phase.
- `README.md`: cấu trúc, công nghệ và cách chạy dự án.
- `AI agent flow.md`: luồng phân tích video/log, đối chiếu claim, tái phân tích và human review.

## Những việc đã hoàn thành

- Khóa hai tổ hợp production hợp lệ:
  - OpenAI + `timestamped_frames` qua `OpenAIVLMService`.
  - Gemini + `native_video` qua `GeminiNativeVideoVLMService`.
- Khóa hai tổ hợp phải bị từ chối khi bootstrap:
  - OpenAI + `native_video`.
  - Gemini + `timestamped_frames`.
- Xác nhận nguyên tắc không tạo fake service; test ở các phase sau phải dùng production service và mock tại SDK boundary.
- Xác nhận graph chỉ phụ thuộc các contract provider-neutral (`VLMService`, `VerificationService`, `ReportService`) và không chọn provider/model.
- Xác nhận context tái phân tích tự động và do con người yêu cầu được tách biệt:
  - Auto: claim mâu thuẫn, lý do verification, log evidence summary, timestamp window và `source="agent_generated"`.
  - Human: target claim IDs, feedback, claims/evidence hiện tại và `source="human_provided"`.
- Xác nhận vòng đời Gemini native video: chuẩn hóa local → upload → poll `PROCESSING` đến `ACTIVE` → phân tích/tái sử dụng remote handle → xóa best-effort khi terminal, fail, hủy hoặc shutdown.
- Xác nhận OpenAI gửi ordered timestamped frames; single request là đường mặc định, rolling batches chỉ là fallback khi vượt giới hạn.

## Thay đổi mã nguồn

Không thay đổi mã nguồn trong `src/` hoặc `tests/`. Đây là chủ ý theo Phase 0 (`Sửa: không`); models, interfaces, settings và provider validation thuộc Phase 1 trở đi.

File được tạo trong lần thực hiện này:

- `work.md`: ghi phạm vi, quyết định, kiểm thử và trạng thái Phase 0.

## Kiểm thử và kiểm tra

Môi trường kiểm tra: `.venv`, Python 3.14.4 (runtime mục tiêu trong kế hoạch là Python 3.11).

| Kiểm tra | Kết quả |
| --- | --- |
| `python3 -m compileall -q src tests` | Pass |
| `.venv/bin/ruff check src tests` | Pass — `All checks passed!` |
| Kiểm tra marker trong `phase.md` bằng `rg` | Pass — đủ capability matrix, auto/human context, Gemini polling/cleanup và no-fake rule |
| Ba API test chạy riêng | Pass — 3/3 |
| LangGraph test | Assertion pass (hiện dấu `.`), nhưng tiến trình pytest không thoát và bị `timeout` với exit code 124 |
| Toàn bộ test suite | Chưa kết thúc sạch; dừng sau test LangGraph đầu tiên do cùng hiện tượng treo khi teardown |

## Lỗi/cảnh báo phát hiện

- Baseline có hiện tượng pytest treo sau khi LangGraph test đã chạy xong assertion. Hiện tượng này tồn tại khi không có thay đổi source của Phase 0 và xảy ra trên Python 3.14.4; cần xác minh lại bằng runtime mục tiêu Python 3.11 trước khi kết luận là lỗi code hay lỗi tương thích môi trường.
- Chưa có assertion nào fail.
- Phase 0 không gọi OpenAI/Gemini thật và không phát sinh chi phí; live smoke test thuộc Phase 9.

## Tiêu chí hoàn thành Phase 0

- [x] Có capability matrix cho OpenAI frames và Gemini native video.
- [x] Có context mẫu/contract cho auto và human re-analysis.
- [x] Có sequence Gemini upload, poll, reuse và cleanup.
- [x] Quyết định không-fake được ghi rõ.
- [x] OpenAI frames và Gemini native video là quyết định chính thức.

**Trạng thái cuối: `complete`.**

---

# Work report — Phase 1

## Trạng thái

`complete`

Phase 1 — Models, interfaces và Settings đã hoàn tất. Phạm vi chỉ gồm contract và cấu hình; chưa gọi SDK OpenAI/Gemini và chưa triển khai media/provider service của Phase 3.

## Những việc đã thực hiện

### Provider-neutral models

Đã tạo `src/models/incidents.py` với:

- Enum cho provider, input mode, analysis mode, verification status và prompt source.
- Hai request type riêng biệt:
  - `TimestampedFramesAnalysisRequest`.
  - `NativeVideoAnalysisRequest`.
- Discriminated union `VideoAnalysisRequest` theo `input_mode`.
- Contract dùng chung: `IncidentWindow`, `PromptEnvelope`, `TimestampedFrame`, `VideoSequenceManifest`, `NativeVideoMetadata` và `SamplingMetadata`.
- Video memory: `VideoMemory`, `VideoMemoryPatch`, entities, timeline, observations, claims, evidence và remote media handles.
- Verification/report request và response models.
- Ba Protocol không phụ thuộc implementation: `VLMService`, `VerificationService`, `ReportService`.

Các validation quan trọng:

- Incident window bắt buộc `t_start <= t0 <= t_end`.
- Video đầu vào không dài quá 60 giây.
- Frame phải có index liên tục, đúng thứ tự timestamp và không vượt duration.
- `VideoMemoryPatch` không được sửa claim ngoài `target_claim_ids`.
- Contract cấm field lạ, giúp API key hoặc provider-specific payload không lọt vào graph state.

### Incident state

Đã tạo `src/agents/incident_state.py` chứa `IncidentState` dạng `TypedDict`, chỉ tham chiếu model/provider-neutral contract. State hỗ trợ lifecycle, memory, claims, verification, report, artifacts, remote handles, re-analysis counters và error/warning.

### Settings và provider matrix

Đã mở rộng `src/config.py` và `.env.example` với các nhóm cấu hình:

- Provider/model và timeout/retry/temperature.
- Gemini Files API.
- Native video preprocessing.
- Timestamped frames, rolling batches và memory limits.
- Prompt versions, verification/report service.
- Incident input limits, log thresholds, artifact/database paths và background concurrency.

Validation khi khởi tạo Settings:

| Provider | Input mode | Kết quả |
| --- | --- | --- |
| OpenAI | `timestamped_frames` | Chấp nhận |
| Gemini | `native_video` | Chấp nhận |
| OpenAI | `native_video` | Từ chối |
| Gemini | `timestamped_frames` | Từ chối |

Settings cũ `model_name` và `llm_temperature` được giữ lại để endpoint baseline tiếp tục tương thích.

## File thay đổi

- Tạo `src/models/incidents.py`.
- Tạo `src/agents/incident_state.py`.
- Tạo `tests/test_models/test_incidents.py` và package test tương ứng.
- Tạo `tests/test_config.py`.
- Sửa `src/config.py`.
- Sửa `.env.example`.
- Sửa `src/models/__init__.py` để export public contracts.
- Cập nhật `work.md`.

## Kiểm thử

Môi trường hiện có: Python 3.14.4; runtime mục tiêu của dự án vẫn là Python 3.11.

| Kiểm tra | Kết quả |
| --- | --- |
| Test model/config Phase 1 | Pass — 12/12 |
| Test Phase 1 + toàn bộ API baseline | Pass — 15/15 |
| `.venv/bin/ruff check src tests` | Pass |
| `python3 -m compileall -q src tests` | Pass |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | Test đầu pass nhưng tiến trình tiếp tục treo ở teardown LangGraph và bị timeout (exit 124) |

Hiện không có assertion failure liên quan Phase 1. Hiện tượng teardown LangGraph đã tồn tại trước Phase 1, tái hiện ngay cả khi tắt plugin LangSmith, và cần được kiểm tra lại trên Python 3.11.

## Tiêu chí hoàn thành Phase 1

- [x] Có hai video request types.
- [x] Có `VideoMemory`, `VideoMemoryPatch`, `RemoteMediaHandle`.
- [x] Có `VLMService`, `VerificationService`, `ReportService` Protocol.
- [x] Có serializable `IncidentState`.
- [x] OpenAI + frames được chấp nhận.
- [x] Gemini + native video được chấp nhận.
- [x] Hai tổ hợp ngược bị từ chối.
- [x] Contract không import OpenAI/Gemini SDK và không có fake implementation.
- [x] Test Phase 1 và lint đều pass.

**Trạng thái cuối Phase 1: `complete`.**

---

# Work report — Phase 2

## Trạng thái

`complete`

Phase 2 — Prompt package đã hoàn tất. Các builder chỉ tạo `PromptEnvelope` provider-neutral; chưa gọi model SDK hoặc thực hiện workflow của các phase sau.

## Những việc đã thực hiện

### Video analysis prompt

Đã tạo `src/prompts/video_analysis.py`:

- `build_video_analysis_prompt()` tạo prompt chung trả structured `VideoMemory`.
- `build_frame_sequence_instruction()` yêu cầu xem ordered frames như một video liên tục và dùng timestamp/frame metadata.
- `build_native_video_instruction()` yêu cầu phân tích uploaded video liên tục với timestamp chính xác.
- Prompt yêu cầu tìm `t_start`, `t0`, `t_end`, track actor/object xuyên thời gian, gắn evidence IDs và không trả chain-of-thought.

### Re-analysis prompts

Đã tạo `src/prompts/reanalysis.py`:

- `build_auto_reanalysis_prompt()` chỉ nhận conflict claim, verification reason, log evidence summary và incident window; nguồn là `agent_generated`.
- `build_human_reanalysis_prompt()` chỉ nhận target claim IDs, feedback, current claims/evidence; nguồn là `human_provided`.
- Validate feedback/reason không rỗng, target ID duy nhất và target claim phải tồn tại.
- Context được serialize JSON ổn định, đặt trong delimiter và được mô tả là dữ liệu thay vì instruction.
- Chỉ yêu cầu sửa targeted claims, không thay đổi claim khác.

### Verification prompt

Đã tạo `src/prompts/verification.py`:

- Nhận claims, log metrics/events/evidence và timestamp tolerance.
- Yêu cầu đúng một result cho mỗi claim, giữ nguyên thứ tự.
- Chỉ cho phép `supported`, `contradicted`, `unverified` và evidence IDs đã cung cấp.
- Từ chối duplicate claim ID hoặc tolerance âm.

### Reporting prompt

Đã tạo `src/prompts/reporting.py`:

- Chỉ yêu cầu các narrative field và evidence IDs của report contract.
- Không cho model viết lại timestamp, metric, incident metadata, artifact location hoặc review state.
- Context loại bỏ `remote_media_handles`, sampling metadata và artifact URI nội bộ.
- Không cho phép khẳng định chắc chắn nguyên nhân khi dữ liệu chỉ hỗ trợ giả thuyết.

### Public package

Đã tạo `src/prompts/__init__.py` để export các builder chính thức. Không prompt module nào import OpenAI/Gemini SDK, Settings, API key hoặc graph state.

## Kiểm thử

Môi trường hiện có: Python 3.14.4; runtime mục tiêu của dự án là Python 3.11.

| Kiểm tra | Kết quả |
| --- | --- |
| Test riêng Phase 2 | Pass — 16/16 |
| Tất cả test trừ baseline LangGraph | Pass — 31/31 |
| `.venv/bin/ruff check src tests` | Pass |
| `python3 -m compileall -q src tests` | Pass |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | LangGraph test đầu hiện dấu pass, sau đó teardown tiếp tục treo và timeout 45 giây, exit 124 |

Không có assertion failure trong test Phase 2 hoặc regression API/model/config. Hiện tượng teardown LangGraph là cảnh báo baseline đã ghi ở Phase 0–1 và không phát sinh từ prompt package.

## Tiêu chí hoàn thành Phase 2

- [x] Có đủ bốn prompt modules và public package.
- [x] Có năm builder chính cùng hai mode-specific instructions.
- [x] Auto/human context tách biệt và có đúng `source`.
- [x] Prompt versioned và deterministic.
- [x] Prompt không nhận raw graph state, Settings, API key hoặc provider client.
- [x] Reporting context không lộ remote Gemini handle hoặc artifact location.
- [x] Structured-output và no-chain-of-thought rules được ghi rõ.
- [x] Test Phase 2, regression không-LangGraph và lint đều pass.

**Trạng thái cuối Phase 2: `complete`.**

---

# Work report — Phase 3

## Trạng thái

`complete`

Phase 3 — Media và hai production VLM services đã hoàn tất. Unit/integration tests không gọi OpenAI hoặc Gemini thật; chúng khởi tạo đúng production adapter và mock tại SDK boundary.

## Những việc đã thực hiện

### Dependencies

Đã bổ sung và kiểm tra:

- `openai>=2.53.0,<3.0.0`.
- `google-genai[aiohttp]>=2.17.0,<3.0.0`.
- `imageio-ffmpeg>=0.6.0`.

Môi trường Phase 3 sử dụng Python 3.11.15, OpenAI SDK 2.53.0, Google Gen AI SDK 2.17.0 và imageio-ffmpeg 0.6.0.

### MediaService

Đã tạo `src/services/media.py` với:

- Probe duration, resolution, FPS và byte size bằng `ffprobe` khi có, fallback sang bundled FFmpeg.
- Validate file tồn tại và video không vượt 60 giây.
- Normalize về MP4 với target width/height/FPS, `fit_pad`, configured codec/pixel format và giới hạn output bytes.
- Giữ audio khi normalize.
- Sample ordered JPEG/PNG frames, gắn `frame_id`, `sequence_index`, `timestamp_s` và delta.
- Async subprocess, timeout và domain error codes; không block event loop bằng `subprocess.run` hoặc `time.sleep`.

### OpenAIVLMService

Đã tạo production `OpenAIVLMService` trong `src/services/vlm.py`:

- Chỉ nhận `TimestampedFramesAnalysisRequest`; từ chối native video.
- Đọc frame local thành Base64 data URL.
- Gửi prompt và toàn bộ ordered frames trong đúng một Responses API request.
- Mỗi image có metadata frame/timestamp ngay trước nó trong content array.
- Dùng `responses.parse(..., text_format=VideoMemory)` và semantic validate lại bằng Pydantic.
- Re-analysis dùng frame manifest và `VideoMemoryPatch` schema.
- Fail trước SDK call khi vượt image limit.
- `release_remote_resources()` là no-op.

### GeminiNativeVideoVLMService

Đã tạo production `GeminiNativeVideoVLMService`:

- Chỉ nhận normalized native MP4; từ chối timestamped frames.
- Upload bằng `client.aio.files.upload()`.
- Poll bất đồng bộ bằng `client.aio.files.get()` và injected async sleep.
- Xử lý `PROCESSING`, `ACTIVE`, `FAILED`, max attempts và processing timeout.
- Gửi video part trước prompt; dùng video metadata/FPS và Pydantic response schema.
- Initial analysis trả `VideoMemory` cùng remote handle.
- Re-analysis reuse ACTIVE handle, áp dụng start/end offset của incident window; có thể upload lại local artifact khi handle mất.
- Cleanup bằng `client.aio.files.delete()`, idempotent và best-effort.
- Tự cleanup file remote khi processing fail/timeout hoặc generation/semantic validation fail.
- Mapping lỗi upload, poll, processing, generation và structured output thành domain error codes.

`ReanalysisRequest` và `VideoMemoryPatch` được mở rộng tối thiểu để mang frame manifest hoặc remote handle mới sau re-upload. Không có fake client/service/class.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Provider/media Phase 3 | Pass — 12/12 |
| Media integration với video thật và FFmpeg thật | Pass — probe, sample frames, normalize MP4 |
| Regression trừ baseline LangGraph | Pass — 43/43 |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/pip check` | Pass — không có dependency conflict |
| `python -m compileall -q src tests` | Pass |
| `git diff --check` | Pass |
| No-fake scan trong `src/` và `tests/` | Pass |
| Toàn bộ pytest suite | LangGraph test đầu pass nhưng teardown baseline vẫn treo; timeout 90 giây, exit 124 |

Provider tests xác nhận:

- OpenAI chỉ có một SDK call và giữ đúng thứ tự hai frame.
- OpenAI overflow dừng trước network boundary.
- Gemini upload → `PROCESSING` → `ACTIVE` → structured result.
- Gemini `FAILED`, upload failure và timeout có đúng error code.
- Gemini re-analysis reuse handle và gửi đúng timestamp window.
- Gemini cleanup không làm terminal flow fail khi remote file đã mất.

Không có outbound model request trong test. Lỗi teardown LangGraph là vấn đề baseline đã được ghi từ các phase trước và không liên quan adapter Phase 3.

## Tiêu chí hoàn thành Phase 3

- [x] Có production MediaService.
- [x] Có production OpenAIVLMService cho timestamped frames.
- [x] Có production GeminiNativeVideoVLMService cho native video.
- [x] OpenAI gửi ordered frames trong một request.
- [x] Gemini upload/poll/generate/delete đầy đủ.
- [x] Có structured output và semantic Pydantic validation.
- [x] Có error mapping và cleanup best-effort.
- [x] Tests mock SDK boundary, không gọi dịch vụ trả phí.
- [x] Không có fake implementation.
- [x] Test Phase 3, regression không-LangGraph, lint và dependency check đều pass.

**Trạng thái cuối Phase 3: `complete`.**

---

# Work report — Phase 4

## Trạng thái

`complete`

Phase 4 — Video Memory Workflow đã hoàn tất. Workflow và agent node chỉ phụ thuộc provider-neutral `VLMService`/capabilities; không import OpenAI SDK, Gemini SDK hoặc concrete provider adapter.

## Những việc đã thực hiện

### VideoMemory workflow

Đã tạo `src/services/video_memory.py` với:

- `VideoMemoryWorkflow` chọn đường chạy dựa trên request type và `VLMCapabilities`.
- `build_sequence_manifest()` tạo/validate ordered sequence manifest.
- `analyze_single_request()` gọi VLM đúng một lần khi frame count nằm trong giới hạn hoặc input là native video.
- `analyze_rolling_batches()` chỉ chạy khi frame count vượt giới hạn request/provider.
- `validate_video_memory()` semantic validate model output và reject thay vì sửa/clamp.
- `merge_video_memory_patch()` merge focused re-analysis patch theo revision và target claim.
- `VideoMemoryWorkflowConfig`/`VideoMemoryLimits` chứa toàn bộ tham số workflow được inject, không đọc Settings trong service/node.

### Single-request frames

- Effective limit là giá trị nhỏ hơn giữa deployment config và provider `max_images_per_request`.
- Khi frame count nhỏ hơn hoặc bằng limit, workflow gọi `vlm.analyze_video()` đúng một lần.
- Backend sở hữu `analysis_mode="single_request"` và sampling metadata.
- Không có request riêng cho từng frame.

### Rolling fallback

- Chia batch liên tiếp theo timestamp với overlap cấu hình.
- Re-index sequence trong từng batch nhưng giữ nguyên `frame_id` và timestamp gốc.
- Batch sau nhận compact memory của batch trước.
- Giới hạn số batch trước khi thực hiện SDK call.
- Chọn representative frames trong provider limit cho synthesis.
- Luôn có một synthesis request cuối tạo memory toàn video.
- Snapshot cuối dùng `analysis_mode="rolling_batches"`, full sampled frame count và batch count.
- Strategy `fail` dừng trước VLM call khi overflow.

### Native video

- Native request gọi cùng `VLMService.analyze_video()` contract.
- Kết quả vẫn là `VideoMemory`, dùng `analysis_mode="native_video"`.
- Không gắn sampling metadata của frame path vào native result.

### Semantic validation

Workflow reject các trường hợp:

- Incident/timeline/claim/observation/evidence timestamp vượt video duration.
- Analysis mode không khớp đường workflow.
- Vượt entity/timeline/claim limits.
- Duplicate entity, observation, claim, evidence hoặc source frame IDs.
- Claim/timeline/observation tham chiếu evidence ID không tồn tại.
- Source frame ID nằm ngoài input batch/video.
- Patch revision cũ, target claim không tồn tại hoặc evidence reference không hợp lệ.

Không timestamp hoặc dữ liệu model nào bị clamp âm thầm.

### Agent node

Đã tạo `src/agents/nodes/incident.py`:

- `analyze_video_node()` validate incident input.
- Với `timestamped_frames`: gọi media sampling, tạo frame request và chạy workflow.
- Với `native_video`: normalize MP4, tạo native request và chạy cùng workflow.
- Dùng prompt builder Phase 2 và version được inject.
- Lưu VideoMemory, claims, remote handles và artifact URIs vào state patch.
- Sanitize incident ID trước khi tạo artifact path.
- Chuyển domain exception thành error code/state mà không import concrete provider errors.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Test riêng Phase 4 | Pass — 13/13 |
| Regression trừ baseline LangGraph | Pass — 56/56 |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/pip check` | Pass |
| `python -m compileall -q src tests` | Pass |
| `git diff --check` | Pass |
| Agent dependency scan | Pass — không import SDK/concrete VLM provider |
| No-fake scan | Pass |
| Toàn bộ pytest suite | Baseline `tests/test_agents/test_graph.py` vẫn treo tại teardown sau test đầu; timeout không có assertion failure mới |

Các test Phase 4 xác nhận:

- Frame count bằng limit vẫn là single request.
- Sáu frame với batch size 3/overlap 1 tạo đúng 3 chronological batches và 1 synthesis call.
- Rolling không chạy khi không overflow.
- Overflow strategy `fail` không gọi VLM.
- Native video trả cùng `VideoMemory` contract.
- Invalid timestamp/evidence bị reject, không clamp.
- Patch chỉ sửa target claim, giữ claim khác và tăng revision.
- Frame/native node gọi đúng media operation theo capability.

## Tiêu chí hoàn thành Phase 4

- [x] Có unified VideoMemory workflow.
- [x] Single-request frames là mặc định.
- [x] Không có per-frame request.
- [x] Rolling chỉ chạy khi vượt limit.
- [x] Rolling có overlap, prior compact memory và final synthesis.
- [x] Native video dùng cùng contract.
- [x] Có semantic validation và focused patch merge.
- [x] Agent node không phụ thuộc concrete provider/SDK/Settings.
- [x] Test Phase 4, regression không-LangGraph và lint đều pass.

**Trạng thái cuối Phase 4: `complete`.**

---

# Work report — Phase 5

## Trạng thái

`complete`

Phase 5 — Incident clip, log analysis và charts đã hoàn tất. Toàn bộ artifact được tạo local theo cách deterministic, không gọi LLM hay dịch vụ ngoài.

## Những việc đã thực hiện

### Incident clip và representative frames

- Mở rộng `MediaService` với `cut_incident_clip()` để cắt chính xác cửa sổ `t_start` đến `t_end` bằng FFmpeg.
- Clip được re-encode theo video codec/pixel format được inject từ workflow config, sau đó probe lại metadata.
- `cut_incident_video_node()` tạo `incident_clip.mp4`, sample frame trong đúng incident window và lưu clip, thư mục frame, representative frame vào `artifact_uris`.
- Sửa race trong nhánh timeout subprocess: chỉ kill FFmpeg khi process còn chạy và không để `ProcessLookupError` che mất `MEDIA_COMMAND_TIMEOUT`.

### Log analysis

- Tạo `LogAnalysisService`, đọc CSV UTF-8/BOM-safe, chuẩn hóa header và validate timestamp không âm, duy nhất, tăng dần.
- Cắt `log_slice.csv` theo inclusive window `[t_start, t_end]`.
- Tính speed start/end/min/max, max brake, max deceleration và max steering change.
- Dùng cột acceleration nếu có; nếu không có thì suy ra m/s² từ speed km/h và delta timestamp.
- Phát hiện brake rise, steering change, autonomy disengagement/driver takeover, warning và error thành `LogEvent` có evidence ID ổn định.
- Log thiếu cột autonomy/warning/error vẫn phân tích bình thường; signal không có không bị suy diễn thành sự kiện.
- Bổ sung `LogEvent`, `LogAnalysisResult`, warnings/errors trong `LogEvidenceSummary` và các field tương ứng trong `IncidentState`.

### Bốn charts

Tạo `ChartService` dùng Matplotlib backend `Agg`, xuất bốn PNG:

1. Speed và acceleration.
2. Brake và throttle.
3. Steering.
4. Autonomy, disengagement, warning/error và các log event.

Cả bốn chart đều có marker `t_start`, `t0`, `t_end`. Dependency `matplotlib>=3.10.0,<4.0.0` đã được thêm và kiểm tra không xung đột.

### Agent state/output

- `analyze_log_node()` gọi log analysis và chart service, sau đó ghi `log_analysis`, `log_evidence_summary`, `log_events`, `chart_uris` và artifact URIs vào state patch.
- Node chỉ phụ thuộc các Protocol provider-neutral; không import Settings, OpenAI/Gemini SDK hoặc concrete VLM provider.
- Các exception có domain code được chuyển thành `error_code`/`error_message` trong state.

## File thay đổi

- Tạo `src/services/log_analysis.py`.
- Tạo `src/services/charts.py`.
- Sửa `src/services/media.py`.
- Sửa `src/agents/nodes/incident.py`.
- Sửa `src/agents/incident_state.py`.
- Sửa `src/models/incidents.py` và `src/models/__init__.py`.
- Sửa `src/services/video_memory.py` cho tham số sample incident frames.
- Sửa `requirements.txt`.
- Tạo `tests/test_services/test_log_analysis.py` và `tests/test_services/test_charts.py`.
- Mở rộng test media và incident node.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Test Phase 5 trực tiếp (log/chart/media/node) | Pass — 14/14 |
| FFmpeg integration trên `data_mock/front_camera.mp4` | Pass — clip 3 giây và metadata hợp lệ |
| Log thật `vehicle_state.csv` | Pass — slice 18 row, brake rise 6.5s, max brake 1.0 |
| Log conflict `vehicle_state_fake.csv` | Pass — không có strong brake rise trong incident window |
| Chart artifacts | Pass — đủ 4 PNG và 3 marker trên mỗi chart |
| Regression trừ baseline LangGraph | Pass — 64/64 |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/python -m compileall -q src tests` | Pass |
| `.venv/bin/pip check` | Pass — không có dependency conflict |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | Hai test đầu hiện `..`, sau đó baseline LangGraph teardown treo; timeout 30 giây, exit 124 |

## Lỗi/cảnh báo

- Không có assertion failure trong 64 test không-LangGraph.
- Lần chạy hồi quy đầu phát hiện race timeout FFmpeg nêu trên; đã sửa và lần chạy lại pass 64/64.
- Hiện tượng pytest không thoát tại test LangGraph vẫn là lỗi baseline đã ghi nhận từ Phase 0–4; không có assertion failure mới do Phase 5.
- Test không gọi OpenAI/Gemini và không phát sinh chi phí API.

## Tiêu chí hoàn thành Phase 5

- [x] Tạo incident clip và representative frames.
- [x] Cắt, validate và phân tích log theo incident window.
- [x] Phân biệt được log thật và log conflict bằng evidence deterministic.
- [x] Tạo đủ bốn chart có `t_start`, `t0`, `t_end`.
- [x] Artifacts và log evidence sẵn sàng cho verification Phase 6.
- [x] Phase tests, regression, lint, compile và dependency check đều pass.

**Trạng thái cuối Phase 5: `complete`.**

---

# Work report — Phase 6

## Trạng thái

`complete`

Phase 6 — OpenAI verification và shared re-analysis đã hoàn tất. Verification dùng structured output, còn auto/human re-analysis dùng chung `VLMService.reanalyze_claims()` cho cả OpenAI timestamped frames và Gemini native video.

## Những việc đã thực hiện

### OpenAI verification service

Đã tạo `src/services/verification.py` với `OpenAIVerificationService`:

- Nhận provider-neutral `VerificationRequest`.
- Dùng verification prompt builder Phase 2 và OpenAI Responses API `responses.parse()`.
- Yêu cầu structured output trực tiếp theo `VerificationResult`.
- Inject model, client/API key, timeout, temperature và prompt version; service không đọc Settings trực tiếp.
- Validate semantic sau structured parsing:
  - Trả đúng một result cho mỗi claim.
  - Claim ID phải đúng thứ tự request.
  - Evidence ID phải nằm trong log evidence đã cung cấp.
- Phân biệt structured-output error và retryable SDK error bằng domain error code.

### Align và verify claims

Đã thêm `align_and_verify_claims_node()`:

- Tạo `VerificationRequest` từ claim trong VideoMemory và deterministic log summary.
- Gọi `VerificationService` Protocol, không import concrete OpenAI service trong node.
- Gán `supported`, `contradicted` hoặc `unverified` vào từng claim.
- Cập nhật nhất quán cả `video_memory`, `claims` và `verification` trong state patch.

### Deterministic routing

Đã tạo `src/agents/incident_routing.py`:

- Có claim `contradicted` và chưa auto retry: route `auto_reanalyze`.
- Không có conflict hoặc đã auto retry một lần: route `draft_report`.
- Thiếu verification result: ném `IncidentRoutingError`, không tự suy diễn route.

### Shared auto/human re-analysis

Đã thêm `auto_reanalyze_node()` và `manual_reanalyze_node()` cùng dùng một helper nội bộ:

- Cả hai đều tạo cùng `ReanalysisRequest` và gọi cùng `workflow.vlm.reanalyze_claims()`.
- Auto prompt chỉ chứa conflict claim, verification reason, log evidence và timestamp window; source là `agent_generated`.
- Human prompt chỉ chứa target claim IDs, feedback, claims/evidence hiện tại; source là `human_provided`.
- Auto node từ chối chạy khi không có conflict và chặn lần chạy thứ hai trước media/SDK call.
- Manual node validate feedback, target IDs và claim tồn tại qua prompt contract.
- Patch được merge bằng `merge_video_memory_patch()`, nên revision và target-claim scope tiếp tục được validate.
- `IncidentState` được bổ sung `review_target_claim_ids` và `review_feedback` cho review lifecycle Phase 8.

### Hai provider path

- OpenAI: resample frame từ video gốc trong đúng `[t_start, t_end]`, dùng `vlm_reanalysis_frame_fps`/max frames đã được map vào workflow config, sau đó gửi ordered frame manifest cho re-analysis.
- Gemini: không sample frames; chuyển remote media handles và normalized local artifact cho adapter. Adapter Phase 3 đã được xác nhận reuse ACTIVE handle, áp dụng video start/end metadata và upload lại local artifact khi handle mất.

## File thay đổi

- Tạo `src/services/verification.py`.
- Tạo `src/agents/incident_routing.py`.
- Sửa `src/agents/nodes/incident.py`.
- Sửa `src/agents/incident_state.py`.
- Sửa `src/models/__init__.py` để export verification/re-analysis contracts.
- Tạo `tests/test_services/test_verification.py`.
- Tạo `tests/test_agents/test_incident_routing.py`.
- Mở rộng `tests/test_agents/test_incident_node.py`.

`src/services/vlm.py` không cần thêm nhánh provider mới: production `reanalyze_claims()` cho OpenAI và Gemini đã được hoàn thành từ Phase 3. Phase 6 kích hoạt và kiểm thử hai nhánh này qua shared node thay vì lặp lại adapter code.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Test Phase 6 và các contract VLM/prompt liên quan | Pass — 46/46 |
| OpenAI verification structured output | Pass |
| Result ordering và evidence allowlist validation | Pass |
| OpenAI frame-window re-analysis | Pass |
| Gemini handle reuse và video start/end metadata | Pass |
| Auto retry limit trước media/SDK call | Pass |
| Auto/human prompt source separation | Pass |
| Regression trừ baseline LangGraph | Pass — 77/77 |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/python -m compileall -q src tests` | Pass |
| `.venv/bin/pip check` | Pass — không có dependency conflict |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | Test LangGraph đầu hiện `.`, sau đó teardown baseline treo; timeout 30 giây, exit 124 |

## Lỗi/cảnh báo

- Không có assertion failure trong 77 test không-LangGraph.
- Full suite vẫn gặp hiện tượng teardown LangGraph baseline đã ghi nhận từ Phase 0–5; không có regression mới từ Phase 6.
- Test mock đúng SDK boundary; không gọi OpenAI/Gemini thật và không phát sinh chi phí API.

## Tiêu chí hoàn thành Phase 6

- [x] Có production `OpenAIVerificationService`.
- [x] Verification semantic-validate claim order và evidence IDs.
- [x] Có deterministic routing cho conflict và auto retry limit.
- [x] Auto/human cùng gọi `VLMService.reanalyze_claims()`.
- [x] OpenAI resample frame incident window.
- [x] Gemini reuse remote native video và timestamp metadata.
- [x] Auto re-analysis chạy tối đa một lần.
- [x] Test Phase 6, regression, lint, compile và dependency check đều pass.

**Trạng thái cuối Phase 6: `complete`.**

---

# Work report — Phase 7

## Trạng thái

`complete`

Phase 7 theo `phase.md` hiện tại — API cho Frontend và lưu quyết định review — đã hoàn tất. Incident API chỉ trả public snapshot theo allowlist; application service gọi/resume graph qua dependency được inject và terminal outcome được lưu bền vững bằng SQLite.

## Những việc đã thực hiện

### Public API contracts

Đã tạo `src/models/api.py` với:

- `IncidentCreateRequest`: incident ID, video URI, log URI tùy chọn, analysis prompt và metadata.
- `ReviewDecision`: `approve | edit | reanalyze | not_incident`, reviewer và payload theo từng action.
- `IncidentSnapshot`: lifecycle status, artifacts, claims/conflicts, re-analysis counters, report, review audit, warning/error và storage timestamp.
- `StoredReport`: terminal outcome đã approve/close.

Validation review được thực hiện trước khi resume workflow:

- `not_incident` bắt buộc có reason.
- `reanalyze` bắt buộc có feedback và target claim IDs duy nhất, không rỗng.
- `edit` chỉ cho sửa sáu prose field của report; không cho sửa timestamp, metric, evidence, status hoặc field lạ.
- Edit value rỗng bị từ chối bằng HTTP 422 trước workflow call.

### Report repository

Đã tạo `src/services/report_repository.py`:

- `ReportRepository` Protocol.
- `InMemoryReportRepository` cho runtime/test nhẹ.
- `SQLiteReportRepository` cho terminal persistence.
- SQLite tự tạo schema tối thiểu và chỉ lưu approved/not-incident outcome, final report, evidence IDs, reviewer, decision, reason và timestamp.
- Mọi query dùng parameter binding.
- Incident ID là primary key; lần ghi terminal thứ hai trả `REPORT_ALREADY_STORED`.
- Dữ liệu được đọc lại đúng từ repository instance mới trên cùng file SQLite.

### Workflow application service

Đã tạo `src/services/workflow.py`:

- `IncidentGraphRunner` Protocol cho `start()` và `resume()`; service không import concrete graph/provider hoặc API key.
- Reserve incident ID và chặn duplicate create.
- Lưu pending snapshot trong memory và có thể khôi phục terminal report từ repository sau khi application service được tạo lại.
- Lock riêng theo incident để serialize các review decision cạnh tranh.
- Chỉ cho review khi status là `awaiting_review`.
- Kiểm tra manual re-analysis target tồn tại trước khi tiêu thụ graph interrupt.
- Khi approve/not-incident, lưu terminal outcome đúng một lần và trả `stored_at`.
- Snapshot mapping chỉ allowlist public field; không trả raw `IncidentState`, prompt, run metadata hay Gemini remote handles.

Pending graph state vẫn là in-memory theo baseline; terminal outcome lưu SQLite có thể đọc sau restart.

### Incident HTTP API

Đã tạo `src/api/incidents.py` và include vào router hiện hữu mà không thay đổi `/chat` hoặc `/status`:

- `POST /api/v1/incidents`.
- `GET /api/v1/incidents/{incident_id}`.
- `POST /api/v1/incidents/{incident_id}/review`.

HTTP behavior:

- `202` cho `queued`, `running`, `awaiting_review`.
- `200` cho terminal snapshot hoặc GET thành công.
- `404` cho incident không tồn tại.
- `409` cho duplicate create, invalid lifecycle, target claim không tồn tại hoặc duplicate terminal storage.
- `422` cho request schema/action payload sai.
- `503 WORKFLOW_SERVICE_UNAVAILABLE` khi bootstrap chưa inject `app.state.incident_workflow_service`.
- Lỗi không mong đợi trả message chung; raw exception, token hoặc stack detail không bị lộ.

`src/api/errors.py` chỉ ánh xạ domain code sang safe HTTP status/detail.

## File thay đổi

- Tạo `src/models/api.py`.
- Tạo `src/services/workflow.py`.
- Tạo `src/services/report_repository.py`.
- Tạo `src/api/incidents.py`.
- Tạo `src/api/errors.py`.
- Sửa `src/api/routes.py` để include incident router.
- Sửa `src/models/__init__.py` để export public API contracts.
- Tạo test repository, workflow và incident API.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Test Phase 7 + API baseline | Pass — 18/18 |
| SQLite reconnect và duplicate terminal write | Pass |
| Create → awaiting review → approve → stored | Pass |
| Edit và not-incident terminal outcomes | Pass |
| Manual re-analysis quay lại awaiting review | Pass |
| Unknown re-analysis target dừng trước runner call | Pass |
| Hai approve cạnh tranh | Pass — một success, một invalid transition, một repository write |
| Duplicate create và review sau terminal | Pass |
| HTTP 200/202/404/409/422/503 mapping | Pass |
| Safe unexpected-error response | Pass — không lộ exception text |
| Regression trừ baseline LangGraph | Pass — 91/91 |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/python -m compileall -q src tests` | Pass |
| `.venv/bin/pip check` | Pass — không có dependency conflict |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | Test LangGraph đầu hiện `.`, sau đó teardown baseline treo; timeout 30 giây, exit 124 |

## Lỗi/cảnh báo

- Không có assertion failure trong 91 test không-LangGraph.
- Full suite vẫn gặp teardown hang của `tests/test_agents/test_graph.py`, là baseline issue đã ghi nhận từ các phase trước.
- Concrete incident graph runner phải được bootstrap inject vào `app.state.incident_workflow_service`; khi chưa inject, API chủ động trả 503 an toàn thay vì tự chọn provider hoặc đọc secret.
- Không có network/model request trong test.

## Tiêu chí hoàn thành Phase 7

- [x] Có ba lifecycle endpoint cho Frontend.
- [x] Giữ nguyên endpoint demo hiện hữu.
- [x] Có safe public snapshot, không trả raw state/private provider data.
- [x] Có duplicate/transition/concurrency protection cơ bản.
- [x] Approve, edit, reanalyze và not-incident có contract xác định.
- [x] Terminal outcome được lưu và đọc lại qua SQLite.
- [x] Test Phase 7, regression, lint, compile và dependency check đều pass.

**Trạng thái cuối Phase 7: `complete`.**

---

# Work report — Phase 8

## Trạng thái

`complete`

Phase 8 — Hardening và nghiệm thu tích hợp đã hoàn tất theo ma trận failure mode trong `phase.md`. Chỉ các lỗi tái hiện được trong phạm vi model/service/agent/API Phase 1–7 mới được sửa; không sửa `src/main.py`, `src/config.py`, dependency files, agent demo cũ hoặc Frontend.

## Ma trận nghiệm thu

### Luồng thành công

- Video-only: workflow tạo snapshot chờ review, report backend bắt buộc ghi `Không có dữ liệu log.` và approve lưu terminal report.
- Video + log không conflict: log analysis, verification và report contract tiếp tục pass trong regression.
- Video + log có conflict: auto node resample incident frames, gọi VLM đúng một lần, merge focused patch và verify lại thành `supported`.
- Conflict vẫn còn sau auto retry: draft report giữ warning `Unresolved contradicted claim` với claim ID; routing count >= 1 không tạo loop VLM thứ hai.

### Failure mode

- OpenAI VLM malformed structured output → `VLM_STRUCTURED_OUTPUT_INVALID`.
- OpenAI VLM timeout → retryable `OPENAI_VIDEO_ANALYSIS_FAILED`.
- Report LLM malformed structured output → `REPORT_STRUCTURED_OUTPUT_INVALID`.
- Report LLM timeout → retryable `OPENAI_REPORT_FAILED` với message an toàn, không lộ provider exception.
- Report LLM trả evidence ID không tồn tại → `REPORT_EVIDENCE_INVALID`.
- Report LLM cố chèn `t_start=999` → Pydantic `extra="forbid"` reject; backend timestamp không bị thay đổi.
- Media cut window vượt video duration → `CLIP_WINDOW_OUT_OF_RANGE` trước khi ghi clip.
- Log thiếu timestamp column → `LOG_TIMESTAMP_MISSING`.
- Runner trả state/status malformed → `WORKFLOW_OUTPUT_INVALID`; incident reservation được dọn để request hợp lệ có thể retry.
- Duplicate incident ID và review sai lifecycle tiếp tục trả conflict xác định.
- Hai review decision cạnh tranh tiếp tục chỉ có một terminal write.

## Các lỗi hardening đã sửa

### Không lộ provider error

Trước Phase 8, `WorkflowService._snapshot()` chuyển nguyên `error_message` từ agent/provider sang public API. Provider exception có thể chứa request detail hoặc secret.

Đã sửa:

- Public snapshot vẫn giữ domain `error_code` để quan sát.
- Raw internal message được thay bằng `incident processing failed`.
- Unexpected API exception tiếp tục được map thành generic safe detail.
- Test chèn `api_key=sk-secret-value` và provider timeout text xác nhận secret không xuất hiện trong snapshot/response.

### Terminal storage retry không chạy lại graph

Trước Phase 8, state terminal được commit vào memory trước khi repository store thành công. Nếu SQLite fail, incident trở thành terminal nhưng chưa được lưu và review retry bị từ chối.

Đã sửa:

- Giữ pending terminal state/decision riêng khi storage fail.
- Public state cũ vẫn `awaiting_review` trong thời gian storage lỗi.
- Retry đúng cùng decision chỉ retry repository, không resume graph/VLM/LLM lần hai.
- Decision khác trong khi terminal storage đang pending bị từ chối.
- Chỉ commit terminal state, audit và `stored_at` sau khi repository ghi thành công.

### Input và runner-output validation

- Incident ID, video URI, analysis prompt, optional log URI và reviewer được strip/validate; chuỗi chỉ có whitespace trả HTTP 422 trước service call.
- State từ graph runner được validate qua public snapshot trước commit.
- Invalid initial result dọn registry/lock/audit reservation; invalid resume result không ghi đè state hợp lệ trước đó.

### Structured report adapter

Acceptance bắt buộc kiểm thử LLM malformed/timeout nhưng workspace chưa có report adapter. Lỗi thiếu này được chứng minh bằng test collection failure, nên đã bổ sung module nhỏ `src/services/reporting.py`:

- `OpenAIReportService` dùng một Responses API structured-output call theo `ReportNarrative`.
- Dùng report prompt đã có, không truyền remote handles/artifact location nội bộ.
- Semantic-validate evidence allowlist từ VideoMemory và log summary.
- Lỗi model/SDK có domain code và safe message.

`build_draft_report_node()` được bổ sung vào node hiện hữu để:

- Gọi provider-neutral `ReportService` Protocol.
- Buộc video-only report ghi rõ không có log.
- Giữ unresolved conflict trong warnings.
- Không cho model thay backend timestamp/metric/status.

## Restart và persistence

- Terminal approved/not-incident outcome đã được test đọc lại từ `SQLiteReportRepository` instance mới.
- Pending `awaiting_review` state/checkpoint vẫn in-memory và có thể mất khi process restart, đúng giới hạn baseline đã công bố; Phase 8 không tự mở rộng sang durable graph checkpointer.
- Pending terminal-storage retry cũng là in-memory; nếu process dừng đúng lúc repository đang fail thì cần resume theo năng lực concrete graph/checkpointer được inject.

## File thay đổi trong Phase 8

- Tạo `src/services/reporting.py` sau khi failure-mode test chứng minh report adapter còn thiếu.
- Sửa `src/agents/nodes/incident.py`.
- Sửa `src/services/workflow.py`.
- Sửa `src/models/api.py` và `src/models/__init__.py`.
- Mở rộng test service, media, log, VLM, agent node và API trong phạm vi hiện có.
- Formatter chuẩn hóa 9 file trong `src/`/`tests/`; chỉ thay đổi layout, không thay logic ngoà các fix nêu trên.

Không sửa `src/main.py`, `src/config.py`, `requirements.txt`, `.env.example`, Docker/CI, module agent demo cũ hoặc Frontend trong Phase 8.

## Kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| Hardening/failure-mode suite trực tiếp | Pass — 59/59 |
| Regression trừ baseline LangGraph | Pass — 107/107 |
| Video-only, log/no-conflict và conflict routing contracts | Pass |
| Conflict → one re-analysis → supported | Pass — đúng một VLM re-analysis call |
| Conflict còn sau count=1 → report warning/no loop | Pass |
| VLM malformed/timeout | Pass |
| Report LLM malformed/timeout/evidence/timestamp guard | Pass |
| Media out-of-range và log missing timestamp | Pass |
| Duplicate create và concurrent review | Pass |
| Terminal storage fail → repository-only retry | Pass |
| SQLite reconnect | Pass |
| Whitespace input và safe error response | Pass |
| No production `Fake*`/`Mock*` class scan | Pass |
| `.venv/bin/ruff format --check src tests` | Pass — 64 files formatted |
| `.venv/bin/ruff check src tests` | Pass |
| `.venv/bin/python -m compileall -q src tests` | Pass |
| `.venv/bin/pip check` | Pass — không có dependency conflict |
| `git diff --check` | Pass |
| Toàn bộ pytest suite | Test LangGraph đầu hiện `.`, sau đó teardown baseline treo; timeout 30 giây, exit 124 |

## Lỗi/cảnh báo còn lại

- Không có assertion failure trong 107 test không-LangGraph.
- `tests/test_agents/test_graph.py` vẫn treo khi teardown sau assertion pass. Đây là baseline issue của agent demo cũ; Phase 8 cấm sửa module demo này nên không che lỗi bằng thay đổi ngoài phạm vi.
- Concrete incident graph/workflow bootstrap vẫn phải được inject; API trả 503 an toàn khi chưa cấu hình.
- Không gọi model/network thật vì không có explicit approval; tests mock SDK boundary và không phát sinh chi phí.

## Tiêu chí hoàn thành Phase 8

- [x] Mọi nhánh acceptance có output hoặc domain error xác định.
- [x] Auto re-analysis không loop vô hạn.
- [x] Structured model không thể ghi đè backend timestamp/metric/status.
- [x] Public API không lộ raw provider error, API key, prompt hoặc remote handle.
- [x] Duplicate/concurrent review và storage failure có hành vi xác định.
- [x] Giới hạn in-memory checkpoint/restart được ghi rõ.
- [x] Formatter, lint, compile, dependency check và regression đều pass.

**Trạng thái cuối Phase 8: `complete`.**

---

# Work report — Phase 9

## Trạng thái

`complete`

Phase 9 — Hoàn thiện end-to-end theo `AI agent flow.md` và bàn giao — đã hoàn tất ngày 2026-08-06. Toàn bộ tiêu chí bắt buộc đã được kiểm tra; model thật không được gọi vì chưa có explicit approval phát sinh chi phí, nên kết quả không được tuyên bố production-ready.

## Những gì đã code

### Báo cáo cố định 10 mục

- Bổ sung `DraftReport` và các typed section cho thông tin chung, incident window, timeline/events, video observations, log summary/metrics, claim verification, evidence/artifacts/warnings và review status.
- Giữ `ReportNarrative` làm structured output sáu trường duy nhất mà LLM được viết.
- `build_draft_report_node()` lắp narrative vào dữ liệu backend; video-only luôn ghi `Không có dữ liệu log.`.
- Timestamp, metric, verification status, evidence/artifact URI, warning và review status đều do backend sở hữu, không nhận giá trị ghi đè từ model.

### Incident LangGraph hoàn chỉnh

- Tạo `src/agents/incident_graph.py` với đầy đủ route video-only, video+log, verification, automatic focused re-analysis, draft report, human review, manual re-analysis, cleanup và fail-fast.
- Mọi router đưa vào LangGraph là async để không phụ thuộc thread executor trong runtime hiện tại.
- Video-only không gọi log/chart/verifier/auto re-analysis.
- Automatic re-analysis gom tất cả contradicted claim vào đúng một focused request thay vì âm thầm chọn claim đầu tiên; counter giới hạn một lần và graph verify lại.
- Conflict còn lại sau lần retry được giữ trong claim status và report warnings, không tạo loop.
- Remote Gemini handles được giữ trong pending checkpoint; terminal/failure cleanup best-effort.

### Human Review interrupt/resume

- Tạo `src/agents/nodes/review.py` dùng LangGraph `interrupt()` và resume bằng `Command` theo `thread_id=incident_id`.
- Interrupt payload chỉ chứa report, artifacts, claims, warnings và action hợp lệ.
- `approve`: cập nhật report approved và kết thúc.
- `edit`: chỉ sửa sáu narrative field, không gọi LLM, giữ `awaiting_review` và interrupt lại.
- `reanalyze`: bắt buộc feedback/target IDs, chạy focused VLM, optional verify, build report lại và quay lại review.
- `not_incident`: bắt buộc reason, lưu audit và đóng case.
- Review audit nằm trong graph state để sống qua process restart.

### Runtime, validation và persistence

- Tạo `src/services/incident_runtime.py` làm concrete dependency factory cho media, OpenAI/Gemini VLM, video-memory workflow, log/chart, verification/report LLM, graph runner, checkpointer và report repository.
- `src/main.py` khởi tạo `incident_workflow_service` trong FastAPI lifespan; cấu hình không hợp lệ trả service-unavailable an toàn thay vì lộ exception/secret.
- Input validator giới hạn configured roots, file tồn tại, kích thước, prompt length và video tối đa 60 giây.
- Bổ sung `langgraph-checkpoint-sqlite` và SQLite checkpoint cho pending workflow.
- Runtime sandbox không cho `aiosqlite` tạo worker thread; đã dùng `SqliteSaver` chính thức với async adapter trực tiếp trên event-loop thread. Checkpoint vẫn là SQLite thật và restart/resume đã pass.
- SQLite terminal repository lưu/đọc lại report 10 mục, artifacts, claims, warnings và toàn bộ review audit; schema cũ được migration thêm cột an toàn.
- `WorkflowService` phục hồi pending state từ runner/checkpointer khi memory registry rỗng và vẫn chống duplicate/concurrent review.

### API và Streamlit test client

- API snapshot dùng `DraftReport`, giữ ba endpoint create/get/review và safe error mapping.
- Tạo `main_test.py` chỉ gọi HTTP API bằng `httpx`; hỗ trợ start, refresh, video/frame/charts, claims, warnings, report 10 mục và bốn review action.
- Thêm dependency Streamlit và checkpoint SQLite, cùng config `INCIDENT_CHECKPOINT_PATH` trong Settings/`.env.example`.
- Cập nhật README với setup, provider matrix, lifecycle, API payload, report contract, persistence, test và giới hạn.
- Không sửa hoặc phụ thuộc frontend hiện hữu.

### Bổ sung upload file — 2026-08-06

- Tạo `src/services/uploads.py` để lưu multipart video/log vào `INCIDENT_UPLOAD_DIR` với filename UUID an toàn.
- Thêm `POST /api/v1/incidents/uploads`: video bắt buộc, log CSV tùy chọn; response trả URI nội bộ cho API tạo incident.
- Video chỉ nhận `.mp4 | .mov | .avi | .mkv | .webm`; log chỉ nhận `.csv`; file rỗng/quá dung lượng/sai extension trả HTTP 422 an toàn.
- Upload video được tự xóa nếu bước upload log sau đó thất bại, không để artifact nửa chừng.
- Input validator tự cho phép configured upload root nhưng vẫn chặn path ngoài root.
- `main_test.py` đã bỏ ô nhập Video URI/Log URI, thay bằng hai `file_uploader`; client tự upload trước rồi tạo incident.
- Bổ sung explicit dependency `python-multipart`, setting `INCIDENT_UPLOAD_DIR`, test endpoint/cleanup và test chuỗi Streamlit upload → create.
- Đã tái hiện upload thật bằng Uvicorn với `front_camera.mp4` và `vehicle_state.csv`: endpoint và đúng hàm `httpx` đều trả HTTP 201 JSON. Nguyên nhân thông báo chung là timeout 180 giây ở request create, ngắn hơn tổng timeout VLM/verification/report có thể có.
- Tăng timeout workflow của Streamlit lên 900 giây và tách rõ thông báo `ConnectError`, `TimeoutException`, HTTP error và response không phải JSON để không che nguyên nhân backend.
- Phân loại `AuthenticationError`, permission/model, quota/rate-limit, timeout và connection error của OpenAI verification thành domain code/message an toàn; không còn che mọi lỗi bằng `OPENAI_VERIFICATION_FAILED`.

### Sửa lỗi full pytest bị treo

- Nguyên nhân được tái hiện là conditional router đồng bộ của demo graph bị LangGraph đưa qua thread executor mà sandbox không hỗ trợ.
- Chuyển duy nhất `should_continue()` sang async; contract và output agent demo không đổi.
- Hai test demo graph và toàn bộ suite hiện kết thúc sạch.

## File chính đã tạo

- `src/agents/incident_graph.py`
- `src/agents/nodes/review.py`
- `src/services/incident_runtime.py`
- `main_test.py`
- `tests/test_agents/test_incident_graph_e2e.py`
- `tests/test_main_test.py`

## File chính đã cập nhật

- `src/models/incidents.py`, `src/models/api.py`, `src/models/__init__.py`
- `src/agents/incident_state.py`, `src/agents/nodes/incident.py`, `src/agents/graph.py`
- `src/services/workflow.py`, `src/services/report_repository.py`
- `src/config.py`, `src/main.py`, `src/api/errors.py`
- `requirements.txt`, `.env.example`, `README.md`, `phase.md`
- Các test contract/repository/workflow liên quan đến semantics report 10 mục và edit non-terminal.

## Kiểm thử và kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| Video-only → review → edit → review | Pass; edit không gọi report LLM |
| Manual re-analysis → report mới → review | Pass |
| Restart SQLite checkpoint → GET/resume approve | Pass |
| Terminal SQLite repository reopen | Pass; report/audit đọc lại đúng |
| Video+log → metrics + 4 charts + verification | Pass với asset thật |
| Conflict → một auto re-analysis → verify lại | Pass; đúng 1 VLM re-analysis call |
| Conflict vẫn còn → report warning/no loop | Pass |
| FastAPI configured lifespan/create/review | Pass; create không trả 503 |
| Not-incident qua API, bắt buộc reason | Pass |
| Streamlit import/API smoke | Pass |
| Uvicorn live startup + `/health` | Pass; HTTP 200, shutdown sạch |
| Streamlit live startup | Pass; server startup và shutdown sạch |
| `ruff check src tests main_test.py` | Pass |
| `ruff format --check src tests main_test.py` | Pass — 72 files formatted |
| `python -m compileall -q src tests main_test.py` | Pass |
| `pip check` | Pass — no broken requirements |
| `git diff --check` | Pass |
| `pytest tests -v --tb=short` | Pass — **123/123**, exit code 0, không treo |

## Lỗi hoặc giới hạn còn lại

- Không có test failure, lint error, format error, compile error hoặc dependency conflict.
- Không gọi OpenAI/Gemini thật vì chưa có explicit approval phát sinh chi phí. E2E dùng production adapters và mock đúng SDK boundary.
- Chưa có authentication/authorization, external object storage, distributed queue hoặc multi-worker production persistence strategy.
- SQLite baseline phù hợp demo/single-process; chưa tuyên bố production-ready.

## Tiêu chí hoàn thành Phase 9

- [x] FastAPI bootstrap workflow service.
- [x] Video-only và video+log chạy đến Human Review.
- [x] Auto re-analysis tối đa một lần và verify lại.
- [x] Report backend-owned đủ 10 mục.
- [x] Approve, edit, manual re-analysis và not-incident đúng flow.
- [x] Pending incident resume sau restart.
- [x] Terminal outcome lưu/đọc lại từ SQLite.
- [x] Streamlit client điều khiển lifecycle qua API.
- [x] Không sửa frontend hiện hữu.
- [x] Lint, format, compile và full pytest exit 0, không treo.
- [x] README và work report phản ánh đúng nghiệm thu thực tế.

**Trạng thái cuối Phase 9: `complete`.**
