# VLens Architecture Diagram

Tài liệu này mô tả kiến trúc hiện tại của VLens: hệ thống tiếp nhận video hành trình và dữ liệu telemetry, dùng AI để trích xuất bằng chứng sự cố, tạo báo cáo và chuyển cho kỹ sư xác nhận.

## 1. System Overview

```mermaid
flowchart LR
    Reviewer["Kỹ sư rà soát"] --> UI["Next.js 15 / React 19<br/>frontend/"]
    UI -->|"REST API và upload media"| API["FastAPI<br/>src/main.py và src/api/"]

    API --> WS["WorkflowService<br/>quản lý vòng đời incident"]
    WS --> GRAPH["LangGraph Incident Workflow<br/>src/agents/incident_graph.py"]

    GRAPH --> VIDEO["Video và CV Pipeline<br/>chuẩn hóa, lấy frame, blur PII, cắt clip"]
    GRAPH --> TELEMETRY["Telemetry Pipeline<br/>phân tích CSV, metric, event và chart"]
    GRAPH --> QWEN["Qwen / DashScope VLM<br/>phân tích video và tái phân tích"]
    GRAPH --> OPENAI["OpenAI Structured Output<br/>verification và report narrative"]

    VIDEO --> FILES[("Local uploads và artifacts")]
    TELEMETRY --> FILES
    GRAPH <--> CHECKPOINT[("SQLite LangGraph checkpointer<br/>incident đang xử lý hoặc chờ review")]
    WS <--> REPORTS[("SQLite report repository<br/>kết quả terminal")]

    GRAPH -.->|"tracing tùy chọn"| LANGSMITH["LangSmith"]
    API --> HEALTH["Health và readiness<br/>/live, /ready"]
```

## 2. Incident Processing Workflow

Các tên node trong sơ đồ dưới đây khớp với graph được khai báo trong `src/agents/incident_graph.py`.

```mermaid
flowchart TD
    START([START]) --> AV["analyze_video"]
    AV --> CE0["map_canonical_evidence<br/>initial phase"]
    CE0 --> HAS_LOG{"Có telemetry?"}

    HAS_LOG -->|"Có"| AL["analyze_log"]
    HAS_LOG -->|"Không"| DR["draft_report"]
    AL --> VERIFY["verify"]

    VERIFY --> RETRY{"Có claim contradicted,<br/>bật auto-reanalysis và chưa retry?"}
    RETRY -->|"Có"| AR["auto_reanalyze"]
    AR --> CEA["map_canonical_evidence<br/>auto phase"]
    CEA --> VERIFY
    RETRY -->|"Không"| DR

    DR --> CUT["cut_incident_video"]
    CUT --> REVIEW["review<br/>LangGraph interrupt"]
    REVIEW --> ACTION{"Quyết định của kỹ sư"}

    ACTION -->|"edit"| REVIEW
    ACTION -->|"reanalyze"| MR["manual_reanalyze"]
    MR --> CEM["map_canonical_evidence<br/>manual phase"]
    CEM --> MANUAL_LOG{"Có telemetry?"}
    MANUAL_LOG -->|"Có"| MV["manual_verify"]
    MANUAL_LOG -->|"Không"| DR
    MV --> DR

    ACTION -->|"approve"| CLEANUP["cleanup"]
    ACTION -->|"not_incident"| CLEANUP
    CLEANUP --> END([END])

    FAILED["Bất kỳ processing node nào<br/>đặt trạng thái failed"] -.-> CLEANUP
```

### Routing rules

- Video là dữ liệu bắt buộc; telemetry là dữ liệu tùy chọn.
- Sau phân tích video, bằng chứng được chuẩn hóa thành canonical evidence trước khi kiểm chứng hoặc tạo báo cáo.
- Nếu có telemetry, mỗi claim được đối chiếu và gán trạng thái `supported`, `contradicted` hoặc `unverified`.
- Auto-reanalysis chỉ chạy khi có claim bị mâu thuẫn, tính năng được bật và incident chưa dùng lượt retry tự động.
- `review` là điểm human-in-the-loop. Workflow tạm dừng tại đây cho tới khi kỹ sư chỉnh sửa, yêu cầu phân tích lại, phê duyệt hoặc kết luận không phải sự cố.
- Các trạng thái terminal được dọn tài nguyên tạm và lưu kết quả vào report repository.

## 3. Data and Evidence Flow

```mermaid
sequenceDiagram
    actor Engineer as Kỹ sư
    participant UI as Next.js UI
    participant API as FastAPI
    participant WF as WorkflowService / LangGraph
    participant Media as Media và CV services
    participant VLM as Qwen VLM
    participant Tel as Telemetry services
    participant LLM as OpenAI
    participant DB as SQLite

    Engineer->>UI: Upload video và telemetry tùy chọn
    UI->>API: Tạo incident
    API->>WF: Khởi chạy workflow
    WF->>Media: Validate, normalize và lấy frame
    WF->>VLM: Phân tích video
    VLM-->>WF: VideoMemory, claims và timestamp

    opt Có telemetry
        WF->>Tel: Phân tích metric, event và chart
        Tel-->>WF: Evidence theo khoảng thời gian
        WF->>LLM: Đối chiếu claim với telemetry
        LLM-->>WF: Verification result
    end

    WF->>LLM: Tạo report narrative có cấu trúc
    LLM-->>WF: Draft report
    WF->>Media: Cắt incident clip
    WF->>DB: Checkpoint trạng thái chờ review
    WF-->>API: Interrupt để human review
    API-->>UI: Claims, evidence, media và report
    Engineer->>UI: Approve, edit, reanalyze hoặc not incident
    UI->>API: Gửi review action
    API->>WF: Resume workflow
    WF->>DB: Lưu trạng thái và kết quả cuối
```

## 4. Main Components

| Layer | Component | Responsibility |
|---|---|---|
| Frontend | `frontend/` | Upload dữ liệu, theo dõi tiến trình, hiển thị incident, evidence, telemetry chart và màn hình review. |
| API | `src/main.py`, `src/api/` | REST endpoints, upload, incident lifecycle, review actions, settings và health checks. |
| Application | `WorkflowService` | Khởi tạo, tiếp tục và truy vấn workflow; kết nối API với LangGraph và persistence. |
| Orchestration | `src/agents/incident_graph.py` | Điều phối toàn bộ pipeline, retry, routing, checkpoint và human-in-the-loop interrupt. |
| Routing | `src/agents/incident_routing.py` | Quyết định nhánh đi tiếp dựa trên phase, telemetry, verification và review action. |
| Video AI | Qwen / DashScope VLM | Phân tích video, tạo VideoMemory, claim, mô tả bằng chứng và tái phân tích theo feedback. |
| Verification và reporting | OpenAI structured output | Đối chiếu bằng chứng telemetry và tạo narrative báo cáo có cấu trúc. |
| Media/CV | Media và CV services | Kiểm tra file, chuẩn hóa video, lấy frame, phát hiện và làm mờ PII, cắt video sự cố. |
| Telemetry | Telemetry services | Đọc dữ liệu xe, tính metric, phát hiện event, dựng chart và tạo evidence theo timestamp. |
| Persistence | SQLite | LangGraph checkpoints cho incident hoạt động và report repository cho kết quả terminal. |
| Observability | LangSmith và model activity | Theo dõi trace AI tùy chọn, trạng thái xử lý và hoạt động model. |

## 5. Persistence and Artifact Ownership

| Data | Storage | Lifecycle |
|---|---|---|
| Video và telemetry tải lên | Local upload storage | Được giữ trong quá trình xử lý; tài nguyên tạm được cleanup khi workflow kết thúc hoặc thất bại. |
| Frame, chart, evidence và incident clip | Local artifact storage | Được tham chiếu bởi incident và báo cáo để kỹ sư rà soát. |
| Workflow state | SQLite LangGraph checkpointer | Lưu trạng thái node, interrupt và dữ liệu cần thiết để resume review. |
| Báo cáo đã phê duyệt hoặc `not_incident` | SQLite report repository | Lưu kết quả terminal để truy xuất sau khi workflow hoàn tất. |
| AI traces | LangSmith, nếu được cấu hình | Dùng cho quan sát và debug; không phải nguồn dữ liệu nghiệp vụ chính. |

## 6. Deployment Boundary

- Frontend và FastAPI là hai runtime độc lập, giao tiếp qua REST API.
- Các provider AI là dịch vụ bên ngoài; API key và model được cấu hình qua settings/environment.
- Baseline hiện tại dùng SQLite và local filesystem. Kiến trúc không phụ thuộc PostgreSQL, ChromaDB hoặc RAG/vector database.
- Health endpoints tách liveness và readiness để kiểm tra tiến trình API và các dependency cần thiết.
