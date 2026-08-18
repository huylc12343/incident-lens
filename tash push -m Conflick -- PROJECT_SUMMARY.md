[1mdiff --git a/.agents/rules/ai-log-hook.md b/.agents/rules/ai-log-hook.md[m
[1mindex e799c12..ac46811 100644[m
[1m--- a/.agents/rules/ai-log-hook.md[m
[1m+++ b/.agents/rules/ai-log-hook.md[m
[36m@@ -10,7 +10,7 @@[m [mLogging prompt vào `.ai-log/session.jsonl` đã được **tự động hoá ho[m
 ## Cơ chế[m
 [m
 Khi student `git push`:[m
[31m-1. Pre-push hook chạy `scripts/log_antigravity.py --auto`, đọc trực tiếp transcript của các conversation Antigravity từ `~/.gemini/antigravity-ide/brain/<conv>/.system_generated/logs/transcript.jsonl` và sweep mọi prompt (`USER_INPUT` + `USER_EXPLICIT`) thuộc về repo hiện tại trong 24 giờ gần nhất.[m
[32m+[m[32m1. Pre-push hook chạy `scripts/log_antigravity.py --auto` và sweep mọi prompt (`USER_INPUT` + `USER_EXPLICIT`) thuộc về repo hiện tại trong 24 giờ gần nhất.[m
 2. Pre-push hook chạy `scripts/submit_log.py`, đẩy `.ai-log/session.jsonl` lên grading server.[m
 [m
 Toàn bộ prompt user đã gõ trong Antigravity IDE được capture **nguyên văn từ disk**, không cần AI tự tóm tắt.[m
[36m@@ -24,7 +24,7 @@[m [mToàn bộ prompt user đã gõ trong Antigravity IDE được capture **nguyên[m
 ## Khi nào cần can thiệp[m
 [m
 - Nếu pre-push hook báo lỗi → báo lại cho user, đừng tự ý bypass `--no-verify`.[m
[31m-- Nếu student dùng tool không nằm trong list auto-hook (ChatGPT, Gemini Web, v.v.) → trỏ họ tới `.agents/workflows/log.md` để log thủ công.[m
[32m+[m[32m- Nếu student dùng tool không nằm trong list auto-hook (ChatGPT, Claude.ai, v.v.) → trỏ họ tới `.agents/workflows/log.md` để log thủ công.[m
 [m
 ## Cài đặt một lần sau khi clone repo[m
 [m
[1mdiff --git a/.agents/workflows/log.md b/.agents/workflows/log.md[m
[1mindex 4b98267..e6934b5 100644[m
[1m--- a/.agents/workflows/log.md[m
[1m+++ b/.agents/workflows/log.md[m
[36m@@ -1,12 +1,12 @@[m
 ---[m
[31m-description: "Ghi log AI thủ công — CHỈ dùng cho web tool (ChatGPT, Gemini Web, Claude.ai, v.v.). KHÔNG dùng cho Antigravity."[m
[32m+[m[32mdescription: "Ghi log AI thủ công — CHỈ dùng cho web tool (ChatGPT, Claude.ai, v.v.). KHÔNG dùng cho Antigravity."[m
 ---[m
 [m
 # Ghi log AI thủ công (chỉ web tool)[m
 [m
[31m-Antigravity IDE, Claude Code, Cursor, Codex, Copilot, Gemini CLI đã **tự động log** qua hook hoặc qua `log_antigravity.py` chạy trong pre-push. **Không cần** chạy lệnh dưới đây cho các tool đó.[m
[32m+[m[32mAntigravity IDE, Claude Code, Cursor, Codex và Copilot đã **tự động log** qua hook hoặc qua `log_antigravity.py` chạy trong pre-push. **Không cần** chạy lệnh dưới đây cho các tool đó.[m
 [m
[31m-Workflow này chỉ dành cho khi bạn dùng **tool web không có hook** — ví dụ ChatGPT, Gemini Web, Claude.ai, Perplexity, v.v.[m
[32m+[m[32mWorkflow này chỉ dành cho khi bạn dùng **tool web không có hook** — ví dụ ChatGPT, Claude.ai, Perplexity, v.v.[m
 [m
 ## Cách chạy[m
 [m
[36m@@ -29,7 +29,6 @@[m [mscripts\_pyrun.cmd scripts\log_manual.py --tool "<tên tool>" --prompt "<mô t[m
 [m
 ```bash[m
 bash scripts/_pyrun.sh scripts/log_manual.py --tool chatgpt --prompt "Brainstorm UI layout for verify page"[m
[31m-bash scripts/_pyrun.sh scripts/log_manual.py --tool gemini-web --prompt "Research risk scoring algorithms"[m
 bash scripts/_pyrun.sh scripts/log_manual.py --tool claude-web --prompt "Explain OAuth2 PKCE flow"[m
 ```[m
 [m
* Unmerged path .codex/hooks.json
* Unmerged path .env.example
[1mdiff --git a/.gemini/settings.json b/.gemini/settings.json[m
[1mdeleted file mode 100644[m
[1mindex 4b479d8..0000000[m
[1m--- a/.gemini/settings.json[m
[1m+++ /dev/null[m
[36m@@ -1,42 +0,0 @@[m
[31m-{[m
[31m-  "hooks": {[m
[31m-    "BeforeAgent": [[m
[31m-      {[m
[31m-        "hooks": [[m
[31m-          {[m
[31m-            "name": "log-prompt",[m
[31m-            "type": "command",[m
[31m-            "command": "bash scripts/_pyrun.sh scripts/log_hook.py --tool=gemini",[m
[31m-            "timeout": 10000[m
[31m-          }[m
[31m-        ][m
[31m-      }[m
[31m-    ],[m
[31m-    "AfterModel": [[m
[31m-      {[m
[31m-        "matcher": ".*",[m
[31m-        "hooks": [[m
[31m-          {[m
[31m-            "name": "log-model",[m
[31m-            "type": "command",[m
[31m-            "command": "bash scripts/_pyrun.sh scripts/log_hook.py --tool=gemini",[m
[31m-            "timeout": 10000[m
[31m-          }[m
[31m-        ][m
[31m-      }[m
[31m-    ],[m
[31m-    "SessionEnd": [[m
[31m-      {[m
[31m-        "matcher": ".*",[m
[31m-        "hooks": [[m
[31m-          {[m
[31m-            "name": "log-session-end",[m
[31m-            "type": "command",[m
[31m-            "command": "bash scripts/_pyrun.sh scripts/log_hook.py --tool=gemini",[m
[31m-            "timeout": 10000[m
[31m-          }[m
[31m-        ][m
[31m-      }[m
[31m-    ][m
[31m-  }[m
[31m-}[m
[1mdiff --git a/.gitignore b/.gitignore[m
[1mindex 900452c..037c96d 100644[m
[1m--- a/.gitignore[m
[1m+++ b/.gitignore[m
[36m@@ -55,6 +55,13 @@[m [mout/[m
 *.pyc[m
 *.pyo[m
 [m
[31m-# AI logs — tracked structure, ignored content[m
[31m-.ai-log/*.jsonl[m
[31m-.ai-log/archive/[m
[32m+[m[32m# Local scripts and AI tooling/logs[m
[32m+[m[32mscripts/[m
[32m+[m[32m.ai-log/[m
[32m+[m[32m.codex/[m
[32m+[m[32m.cursor/[m
[32m+[m[32m.claude/[m
[32m+[m[32m.windsurf/[m
[32m+[m[32m.aider/[m
[32m+[m[32m.continue/[m
[32m+[m[32m.amazonq/[m
[1mdiff --git a/.streamlit/config.toml b/.streamlit/config.toml[m
[1mnew file mode 100644[m
[1mindex 0000000..9608164[m
[1m--- /dev/null[m
[1m+++ b/.streamlit/config.toml[m
[36m@@ -0,0 +1,2 @@[m
[32m+[m[32m[server][m
[32m+[m[32mmaxUploadSize = 10240[m
[1mdiff --git a/ARCHITECTURE.md b/ARCHITECTURE.md[m
[1mindex 54f75f1..5dbc664 100644[m
[1m--- a/ARCHITECTURE.md[m
[1m+++ b/ARCHITECTURE.md[m
[36m@@ -36,16 +36,19 @@[m [mgraph TB[m
 ## Components[m
 [m
 ### 1. Frontend (React/Next.js)[m
[32m+[m
 - **Purpose:** [mô tả][m
 - **Key Features:** [danh sách][m
 - **State Management:** [approach][m
 [m
 ### 2. Backend (FastAPI)[m
[32m+[m
 - **Purpose:** [mô tả][m
 - **API Design:** RESTful[m
 - **Authentication:** [JWT/None][m
 [m
 ### 3. AI Agent (LangGraph)[m
[32m+[m
 - **Agent Type:** [ReAct / Plan-and-Execute / Custom][m
 - **State:** [mô tả state schema][m
 - **Nodes:** [danh sách nodes][m
[36m@@ -63,11 +66,13 @@[m [mgraph LR[m
 ```[m
 [m
 ### 4. Database[m
[32m+[m
 - **Type:** [PostgreSQL / SQLite][m
 - **Tables:** [danh sách][m
 - **Migrations:** Alembic[m
 [m
 ### 5. Vector Store[m
[32m+[m
 - **Type:** [ChromaDB / FAISS / Pinecone][m
 - **Embeddings:** [model][m
 - **Purpose:** [RAG / similarity search][m
[36m@@ -102,9 +107,9 @@[m [mgraph LR[m
 [m
 ## Design Decisions[m
 [m
[31m-| Decision | Choice | Reason |[m
[31m-|----------|--------|--------|[m
[31m-| Framework | FastAPI | Async, auto-docs, type-safe |[m
[31m-| Agent | LangGraph | Flexible state management |[m
[31m-| Database | [choice] | [reason] |[m
[31m-| Frontend | Next.js | [reason] |[m
[32m+[m[32m| Decision  | Choice    | Reason                      |[m
[32m+[m[32m| --------- | --------- | --------------------------- |[m
[32m+[m[32m| Framework | FastAPI   | Async, auto-docs, type-safe |[m
[32m+[m[32m| Agent     | LangGraph | Flexible state management   |[m
[32m+[m[32m| Database  | [choice]  | [reason]                    |[m
[32m+[m[32m| Frontend  | Next.js   | [reason]                    |[m
[1mdiff --git a/Dockerfile b/Dockerfile[m
[1mindex 1ac33fd..72f6f34 100644[m
[1m--- a/Dockerfile[m
[1m+++ b/Dockerfile[m
[36m@@ -29,6 +29,6 @@[m [mUSER appuser[m
 EXPOSE 8000[m
 [m
 HEALTHCHECK --interval=30s --timeout=10s --retries=3 \[m
[31m-    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1[m
[32m+[m[32m    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')" || exit 1[m
 [m
 CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"][m
[1mdiff --git a/README.md b/README.md[m
[1mindex e0d5f21..4161465 100644[m
[1m--- a/README.md[m
[1m+++ b/README.md[m
[36m@@ -1,201 +1,195 @@[m
[31m-# 🤖 AI20K Agent Template[m
[32m+[m[32m# Incident Analysis Agent[m
[32m+[m
[32m+[m[32mBackend FastAPI + LangGraph phân tích video giao thông dưới 60 giây, kết hợp log xe tùy chọn, tạo báo cáo 10 mục và dừng tại bước kỹ thuật viên review. Dự án có Streamlit client độc lập trong `main_test.py` để chạy toàn bộ lifecycle qua HTTP API.[m
[32m+[m
[32m+[m[32m## Luồng xử lý[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mvideo + optional log[m
[32m+[m[32m  → VLM tìm t_start, t0, t_end, timeline và claims[m
[32m+[m[32m  → cắt incident clip + representative frames[m
[32m+[m[32m  → nếu có log: cắt log + metrics/events + 4 charts + verify claims[m
[32m+[m[32m  → nếu có conflict: focused VLM re-analysis tối đa 1 lần + verify lại[m
[32m+[m[32m  → backend lắp báo cáo cố định 10 mục[m
[32m+[m[32m  → LangGraph interrupt chờ human review[m
[32m+[m[32m  → approve | edit | reanalyze | not_incident[m
[32m+[m[32m  → SQLite checkpoint + terminal report repository[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32m`edit` chỉ sửa sáu trường narrative và quay lại `awaiting_review`; không tự approve và không gọi LLM. `reanalyze` bắt buộc có feedback cùng target claim IDs, sau đó tạo lại báo cáo và quay lại review. Chỉ `approve` và `not_incident` là terminal.[m
[32m+[m
[32m+[m[32m## Cài đặt[m
[32m+[m
[32m+[m[32mYêu cầu Python 3.11 và FFmpeg. `MediaService` ưu tiên `ffmpeg`/`ffprobe` trong `PATH`; package `imageio-ffmpeg` cung cấp fallback cho FFmpeg.[m
[32m+[m
[32m+[m[32m```bash[m
[32m+[m[32mpython3.11 -m venv .venv[m
[32m+[m[32msource .venv/bin/activate[m
[32m+[m[32mpip install -r requirements.txt[m
[32m+[m[32mcp .env.example .env[m
[32m+[m[32m```[m
 [m
[31m-Template chính thức cho học viên **VinUni AI20K Build Phase** — cung cấp sẵn cấu trúc dự án, code mẫu, và hướng dẫn kỹ thuật chi tiết để xây dựng AI Agent đạt điểm cao (35+/50).[m
[32m+[m[32mCấu hình tối thiểu cho OpenAI timestamped frames:[m
[32m+[m
[32m+[m[32m```dotenv[m
[32m+[m[32mOPENAI_API_KEY=...[m
[32m+[m[32mVLM_PROVIDER=openai[m
[32m+[m[32mVLM_INPUT_MODE=timestamped_frames[m
[32m+[m[32mINCIDENT_INPUT_ROOTS=./data_mock[m
[32m+[m[32mINCIDENT_UPLOAD_DIR=./data/uploads[m
[32m+[m[32mARTIFACT_DIR=./data/artifacts[m
[32m+[m[32mINCIDENT_DATABASE_PATH=./data/incident_reports.sqlite3[m
[32m+[m[32mINCIDENT_CHECKPOINT_PATH=./data/incident_checkpoints.sqlite3[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mIncident clip mặc định có tối thiểu 5 giây, thêm 1 giây trước và 2 giây sau window do VLM xác định. Có thể điều chỉnh bằng `INCIDENT_CLIP_MIN_DURATION_S`, `INCIDENT_CLIP_PRE_ROLL_S` và `INCIDENT_CLIP_POST_ROLL_S`. Ảnh `representative_frame` được chọn gần `t0` thay vì lấy frame đầu tiên.[m
[32m+[m
[32m+[m[32mKhi incident có log, bước phân tích video nhận thêm một `log_attention_hint` định tính để biết timestamp nào cần xem kỹ. Hint chỉ mô tả ga thay đổi quá `0.2`, phanh thay đổi quá `0.5` hoặc góc đánh lái thay đổi quá `0.3`; tối đa 20 timestamp. Gia tốc không được dùng để tạo attention hint. VLM không nhận giá trị telemetry cụ thể, raw log hay evidence ID và không được dùng hint để kết luận tai nạn.[m
 [m
[31m-> 📖 **Technical Guidebook:** [phoenix.note.transformerlabs.ai/technical-book](https://phoenix.note.transformerlabs.ai/technical-book)[m
[32m+[m[32mKhi đối chiếu claim với log, backend trước tiên chỉ giữ các dòng đồng thời nằm trong `incident_window` và `±LOG_TIMESTAMP_TOLERANCE_S` quanh timestamp của claim. `LOG_CLAIM_SAMPLE_RADIUS` sau đó giới hạn số mẫu lấy ở mỗi phía của mẫu gần nhất; mặc định `3` tạo tối đa 7 mẫu. Các dòng model nhìn thấy và `allowed_evidence_ids` luôn là cùng một tập. Nếu không có dòng hợp lệ, claim được giữ ở trạng thái `unverified`.[m
 [m
[31m-## 🎯 Template này dùng để làm gì?[m
[32m+[m[32mGia tốc suy ra từ tốc độ có trị tuyệt đối lớn hơn `15 m/s²` được xem là outlier, không đưa vào metric verification. Backend ghi `LOG_ACCELERATION_OUTLIER_FILTERED` trong warnings để việc lọc không diễn ra âm thầm. Rule này chỉ lọc metric gia tốc bất thường, không tự kết luận có hoặc không có va chạm.[m
 [m
[31m-Khi tham gia AI20K Build Phase, mỗi đội cần xây dựng một AI Agent hoàn chỉnh — từ kiến trúc, code, test, đến deploy. Thay vì bắt đầu từ con số không, template này cung cấp:[m
[32m+[m[32mQwen native video dùng `VLM_PROVIDER=qwen`, `VLM_INPUT_MODE=native_video` và `DASHSCOPE_API_KEY`. Video được resize/pad theo `VLM_VIDEO_TARGET_WIDTH`, `VLM_VIDEO_TARGET_HEIGHT` và chuẩn hóa FPS trước khi gửi. Video local nhỏ hơn `QWEN_BASE64_MAX_VIDEO_BYTES` (mặc định 7 MB) được gửi bằng Base64 Data URL. Video lớn hơn ngưỡng cần `QWEN_ARTIFACT_URL_BASE` công khai `ARTIFACT_DIR`. Qwen gọi `qwen3-vl-flash` qua DashScope chat completions.[m
 [m
[31m-- **Cấu trúc thư mục chuẩn** — đã được thiết kế theo best practices (separation of concerns)[m
[31m-- **Code mẫu** cho các phần cốt lõi: LangGraph agent, FastAPI API, config, schemas[m
[31m-- **Docker + CI/CD sẵn** — Dockerfile multi-stage, GitHub Actions workflow[m
[31m-- **Hướng dẫn kỹ thuật 10 chương** — từ clone template đến nộp bài Demo Day[m
[31m-- **Checklist 10 deliverables** — đảm bảo không bỏ sót yêu cầu BTC[m
[31m-- **AI Usage Logging tự động** — Pre-configured hooks cho Claude Code, Cursor, Codex, Gemini CLI, Antigravity, và GitHub Copilot[m
[32m+[m[32mStreamlit upload file vào `INCIDENT_UPLOAD_DIR`; ngưỡng mặc định 200 MB của Streamlit được nâng lên 10 GB và backend không giới hạn dung lượng video. Backend vẫn kiểm tra phần mở rộng, path root, file tồn tại và video không quá 60 giây. File log vẫn chịu giới hạn `INCIDENT_MAX_LOG_BYTES`. URL từ xa và external object storage không thuộc baseline.[m
 [m
[31m-## ⚡ Quick Start[m
[32m+[m[32m## Chạy backend và Streamlit[m
 [m
[31m-### Bước 1: Fork hoặc Clone[m
[32m+[m[32mTerminal 1:[m
 [m
 ```bash[m
[31m-# Clone template[m
[31m-git clone https://github.com/AI20K-Build-Cohort-2/starter-code-template.git team-YOUR_TEAM_NAME[m
[31m-cd team-YOUR_TEAM_NAME[m
[31m-[m
[31m-# Xóa git history cũ và khởi tạo lại[m
[31m-rm -rf .git[m
[31m-git init[m
[31m-git add .[m
[31m-git commit -m "feat: khởi tạo dự án từ template"[m
[32m+[m[32muvicorn src.main:app --reload --port 8000[m
 ```[m
 [m
[31m-### Bước 2: Setup môi trường[m
[32m+[m[32mTerminal 2:[m
 [m
 ```bash[m
[31m-# Tạo virtual environment[m
[31m-python3.11 -m venv .venv[m
[31m-source .venv/bin/activate[m
[32m+[m[32mstreamlit run main_test.py[m
[32m+[m[32m```[m
 [m
[31m-# Cài dependencies[m
[31m-pip install -e ".[dev]"[m
[32m+[m[32mSwagger: `http://localhost:8000/docs`.[m
 [m
[31m-# Cấu hình API keys[m
[31m-cp .env.example .env[m
[31m-# Mở .env và thêm OPENAI_API_KEY của bạn[m
[31m-# Đồng thời cập nhật AI_LOG_API_KEY bằng key riêng từ link mời của BTC[m
[31m-# (giá trị trong .env.example chỉ là placeholder)[m
[32m+[m[32m### LangSmith tracing[m
[32m+[m
[32m+[m[32mTracing là tùy chọn và không thay đổi routing, retry, checkpoint hoặc output của workflow. Để bật tracing, tạo API key trong LangSmith rồi cấu hình `.env`:[m
[32m+[m
[32m+[m[32m```dotenv[m
[32m+[m[32mLANGSMITH_TRACING=true[m
[32m+[m[32mLANGSMITH_API_KEY=lsv2_...[m
[32m+[m[32mLANGSMITH_PROJECT=incident-analysis-dev[m
[32m+[m[32mLANGSMITH_TRACING_SAMPLING_RATE=1.0[m
 ```[m
 [m
[31m-### Bước 3: Cài AI Logging Hooks[m
[32m+[m[32mNếu API key thuộc nhiều workspace, thêm `LANGSMITH_WORKSPACE_ID`. Khởi động lại backend sau khi đổi `.env`. Mỗi incident được gắn `thread_id=incident_id`; lần chạy đầu và các lần resume/reanalysis vì vậy xuất hiện trong cùng một LangSmith thread. Model calls từ OpenAI Responses API và Qwen OpenAI-compatible API được hiển thị dưới graph trace. Raw ảnh/video Base64, signed media URL và API key được lọc trước khi gửi.[m
 [m
[31m-```bash[m
[31m-# Linux / macOS / Git Bash[m
[31m-bash scripts/setup_hooks.sh[m
[32m+[m[32mĐể tắt hoàn toàn, đặt `LANGSMITH_TRACING=false`. Thiếu `LANGSMITH_API_KEY` cũng khiến integration tự tắt; lỗi gửi trace không làm incident workflow thất bại.[m
 [m
[31m-# Windows PowerShell[m
[31m-# powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1[m
[31m-```[m
[32m+[m[32mTrong Streamlit, chọn video bằng nút **Browse files** và chọn log CSV nếu có; không cần nhập đường dẫn file.[m
 [m
[31m-Hooks tự động log mọi AI prompt khi dùng Claude Code, Cursor, Codex, Gemini CLI, Antigravity, hoặc GitHub Copilot. Không cần thao tác thủ công.[m
[32m+[m[32mWorkflow chạy đồng bộ đến Human Review nên VLM + verification + report có thể mất vài phút. Streamlit chờ tối đa 900 giây và hiển thị riêng lỗi kết nối, timeout hoặc response backend không phải JSON; xem terminal Uvicorn nếu backend báo HTTP 500.[m
 [m
[31m-### Bước 4: Chạy server[m
[32m+[m[32mNếu OpenAI verification thất bại, workflow không còn kết thúc bằng lỗi: snapshot ghi warning và backend tạo báo cáo fallback từ `video_summary`, timeline và evidence trong claims mà VLM đã trả. Khi verification của incident có log không khả dụng, lần gọi report model được bỏ qua. Sau khi sửa `.env` hoặc cập nhật code, phải khởi động lại FastAPI và dùng incident ID mới vì incident cũ vẫn có checkpoint.[m
 [m
[31m-```bash[m
[31m-# Chạy FastAPI backend[m
[31m-uvicorn src.main:app --reload --port 8000[m
[32m+[m[32m## Incident API[m
[32m+[m
[32m+[m[32m### Upload video và log[m
 [m
[31m-# Mở Swagger UI[m
[31m-# http://localhost:8000/docs[m
[32m+[m[32m```http[m
[32m+[m[32mPOST /api/v1/incidents/uploads[m
[32m+[m[32mContent-Type: multipart/form-data[m
[32m+[m
[32m+[m[32mvideo=<video file, bắt buộc>[m
[32m+[m[32mlog=<CSV file, tùy chọn>[m
 ```[m
 [m
[31m-### Bước 5: Đọc hướng dẫn[m
[32m+[m[32mVideo hỗ trợ `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`; log hỗ trợ `.csv`. Response trả `video_uri` và `log_uri` nội bộ để dùng trong request tạo incident.[m
 [m
[31m-📖 Mở **[Technical Guidebook](https://phoenix.note.transformerlabs.ai/technical-book)** và làm theo từng chương.[m
[32m+[m[32m### Tạo incident[m
 [m
[31m-## 📁 Cấu trúc dự án[m
[32m+[m[32m```http[m
[32m+[m[32mPOST /api/v1/incidents[m
[32m+[m[32mContent-Type: application/json[m
 [m
[32m+[m[32m{[m
[32m+[m[32m  "incident_id": "INC-001",[m
[32m+[m[32m  "video_uri": "data_mock/front_camera.mp4",[m
[32m+[m[32m  "log_uri": "data_mock/vehicle_state.csv",[m
[32m+[m[32m  "analysis_prompt": "Phân tích sự cố trong video."[m
[32m+[m[32m}[m
 ```[m
[31m-├── src/[m
[31m-│   ├── agents/           # 🧠 LangGraph Agent[m
[31m-│