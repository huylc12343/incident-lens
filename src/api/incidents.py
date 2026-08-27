"""HTTP endpoints for the incident analysis lifecycle."""

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from src.api.errors import incident_http_error
from src.models.api import (
    IncidentCreateRequest,
    IncidentDeleteResponse,
    IncidentHistoryResponse,
    IncidentSnapshot,
    IncidentUploadResponse,
    ReviewDecision,
    StoredReportsResponse,
)

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
        create_detached = getattr(service, "create_detached", None)
        snapshot = await create_detached(payload) if create_detached is not None else await service.create(payload)
    except Exception as exc:
        raise incident_http_error(exc) from exc
    response.status_code = _response_status(snapshot)
    return snapshot


@router.get("", response_model=IncidentHistoryResponse)
async def list_incident_history(
    service: Any = Depends(get_workflow_service),
) -> IncidentHistoryResponse:
    try:
        incident_ids = await service.list_incident_ids()
    except Exception as exc:
        raise incident_http_error(exc) from exc
    return IncidentHistoryResponse(incident_ids=incident_ids, count=len(incident_ids))


@router.get("/reports", response_model=StoredReportsResponse)
async def list_stored_reports(
    service: Any = Depends(get_workflow_service),
) -> StoredReportsResponse:
    try:
        reports = await service.list_reports()
    except Exception as exc:
        raise incident_http_error(exc) from exc
    return StoredReportsResponse(reports=reports, count=len(reports))


@router.get("/{incident_id}", response_model=IncidentSnapshot)
async def get_incident(
    incident_id: str,
    service: Any = Depends(get_workflow_service),
) -> IncidentSnapshot:
    try:
        return await service.get(incident_id)
    except Exception as exc:
        raise incident_http_error(exc) from exc


@router.delete("/{incident_id}", response_model=IncidentDeleteResponse)
async def delete_incident(
    incident_id: str,
    service: Any = Depends(get_workflow_service),
) -> IncidentDeleteResponse:
    try:
        await service.delete(incident_id)
    except Exception as exc:
        raise incident_http_error(exc) from exc
    return IncidentDeleteResponse(incident_id=incident_id, deleted=True)


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
