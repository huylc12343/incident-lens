from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.config import get_settings
from src.services.incident_runtime import incident_workflow_service
from src.services.uploads import IncidentUploadService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    app.state.incident_upload_service = IncidentUploadService(
        upload_dir=settings.incident_upload_dir,
        max_video_bytes=settings.incident_max_video_bytes,
        max_log_bytes=settings.incident_max_log_bytes,
    )
    try:
        runtime = incident_workflow_service(settings)
        service = await runtime.__aenter__()
    except Exception:
        app.state.incident_workflow_startup_error = "Incident workflow configuration is unavailable."
        try:
            yield
        finally:
            del app.state.incident_upload_service
            print("Shutting down...")
    else:
        app.state.incident_workflow_service = service
        try:
            yield
        finally:
            del app.state.incident_workflow_service
            del app.state.incident_upload_service
            await runtime.__aexit__(None, None, None)
            print("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
