# Team Guide

Mọi người kéo nhánh `develop` về và làm việc.

Đặt tên nhánh ví dụ:

- Role AI Agent: `feature/ai-brain`
- Role giao diện: `feature/frontend-mvp`
- Role dataset: `feature/dataset`
- Role CV: `feature/cv-pipeline`

## Luồng làm việc Team

```text
User
    │
    ▼
Frontend (Vue)
    │
    ▼
FastAPI Backend
    │
    ▼
AI Agent (LangGraph)
    │
    ├── CV Service
    │      ├── Read Video
    │      ├── Event Candidate Detection
    │      └── Clip Extraction
    │
    ├── Log Analysis Service
    │
    ├── VLM Service
    │
    └── LLM Report Service
    │
    ▼
Incident Report JSON
    │
    ▼
FastAPI
    │
    ▼
Frontend
```

## Hướng dẫn nơi làm việc

### 1. Frontend

#### Thư mục làm việc

```text
frontend/
├── src/
│   ├── assets/
│   ├── components/
│   ├── views/
│   ├── router/
│   ├── stores/
│   └── services/
```

#### Phụ trách

- UI/UX
- Upload Video
- Upload CSV
- Processing Screen
- Timeline
- Incident Report
- Human Review
- Call FastAPI API

#### Không làm

- Không gọi VLM trực tiếp
- Không xử lý AI
- Không xử lý video

### 2. Backend (FastAPI)

#### Thư mục làm việc

```text
src/api/
src/models/
src/services/storage/
src/services/jobs/
```

#### Phụ trách

- API
- Upload file
- Validate request
- Lưu file
- Gọi AI Agent
- Trả kết quả cho Frontend
- Quản lý Job Status

#### Không làm

- Không viết Prompt
- Không xử lý CV
- Không gọi VLM trực tiếp

### 3. Dataset & CARLA

#### Thư mục làm việc

```text
dataset/
docs/

dataset/
├── metadata/
├── samples/
├── scripts/
└── carla/
```

#### Phụ trách

- Research Dataset
- Download Dataset
- Dataset Structure
- Label Definition
- Ground Truth
- CARLA Scenario
- Export Video + Log

### 4. Computer Vision (CV)

#### Thư mục làm việc

```text
src/services/video/
src/services/cv/
src/agents/nodes/
```

#### Phụ trách

- Video Reading
- Frame Sampling
- Event Candidate Detection
- Clip Extraction
- Timestamp Synchronization
- YOLO (nếu dùng)

#### Output

```text
Long Video
    ↓
Candidate Clip
    ↓
Timestamp
```

#### Không làm

- Không sinh report
- Không viết Prompt
- Không xử lý UI

### 5. AI Brain

#### Thư mục làm việc

```text
src/agents/
src/services/vlm/
src/services/llm/
src/services/logs/
```

#### Phụ trách

- LangGraph Workflow
- State
- Nodes
- Prompt Engineering
- VLM
- LLM
- Evidence Fusion
- Report Generation
