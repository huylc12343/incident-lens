"""HTTP endpoints for the incident analysis lifecycle."""

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from src.api.errors import incident_http_error
from src.models.api import IncidentCreateRequest, IncidentSnapshot, IncidentUploadResponse, ReviewDecision

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def get_workflow_service(request: Request) -> Any:
    service = getattr(request.app.state, "incident_workflow_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "WORKFLOW_SERVICE_UNAVAILABLE",
                "message": "incident workflow service is not configured",
            },
        )
    return service


async def get_upload_service(request: Request) -> Any:
    service = getattr(request.app.state, "incident_upload_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "UPLOAD_SERVICE_UNAVAILABLE", "message": "incident upload service is not configured"},
        )
    return service


@router.post("/uploads", response_model=IncidentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_incident_files(
    video: UploadFile = File(...),
    log: UploadFile | None = File(default=None),
    service: Any = Depends(get_upload_service),
) -> IncidentUploadResponse:
    try:
        return await service.save(video, log)
    except Exception as exc:
        raise incident_http_error(exc) from exc


@router.post("", response_model=IncidentSnapshot, status_code=status.HTTP_202_ACCEPTED)
async def create_incident(
    payload: IncidentCreateRequest,
    response: Response,
    service: Any = Depends(get_workflow_service),
) -> IncidentSnapshot:
    try:
        snapshot = await service.create(payload)
    except Exception as exc:
        raise incident_http_error(exc) from exc
    response.status_code = _response_status(snapshot)
    return snapshot


@router.get("/{incident_id}", response_model=IncidentSnapshot)
async def get_incident(
    incident_id: str,
    service: Any = Depends(get_workflow_service),
) -> IncidentSnapshot:
    try:
        return await service.get(incident_id)
    except Exception as exc:
        raise incident_http_error(exc) from exc


@router.post("/{incident_id}/review", response_model=IncidentSnapshot)
async def review_incident(
    incident_id: str,
    payload: ReviewDecision,
    response: Response,
    service: Any = Depends(get_workflow_service),
) -> IncidentSnapshot:
    try:
        snapshot = await service.review(incident_id, payload)
    except Exception as exc:
        raise incident_http_error(exc) from exc
    response.status_code = _response_status(snapshot)
    return snapshot


def _response_status(snapshot: IncidentSnapshot) -> int:
    if snapshot.status in {"queued", "running", "awaiting_review"}:
        return status.HTTP_202_ACCEPTED
    return status.HTTP_200_OK
