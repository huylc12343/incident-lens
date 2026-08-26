import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.config import get_settings
from src.services.incident_runtime import incident_workflow_service
from src.services.uploads import IncidentUploadService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    app.state.incident_upload_service = IncidentUploadService(
        upload_dir=settings.incident_upload_dir,
        max_log_bytes=settings.incident_max_log_bytes,
    )
    try:
        runtime = incident_workflow_service(settings)
        service = await runtime.__aenter__()
    except Exception:
        logger.exception("Incident workflow startup failed")
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
app.mount(
    "/artifacts",
    StaticFiles(directory=settings.artifact_dir, check_dir=False),
    name="artifacts",
)


@app.get("/health")
async def health():
    return {"status": "live", "env": settings.app_env}


@app.get("/live")
async def live():
    return {"status": "live", "env": settings.app_env}


@app.get("/ready")
async def ready():
    service = getattr(app.state, "incident_workflow_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "WORKFLOW_NOT_READY", "message": "workflow initialization is incomplete"},
        )
    try:
        await service.ready()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "WORKFLOW_NOT_READY", "message": "workflow dependency check failed"},
        ) from exc
    return {"status": "ready", "env": settings.app_env}
