from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.main import app
from src.models.api import IncidentSnapshot
from src.services.workflow import WorkflowError


def _snapshot(status: str = "awaiting_review") -> IncidentSnapshot:
    return IncidentSnapshot(
        incident_id="INC-HTTP",
        status=status,
        has_log=False,
        artifact_uris={"incident_clip": "storage://clip.mp4"},
    )


@pytest.mark.asyncio
async def test_incident_api_create_get_and_approve(client) -> None:
    service = SimpleNamespace(
        create=AsyncMock(return_value=_snapshot()),
        get=AsyncMock(return_value=_snapshot()),
        review=AsyncMock(return_value=_snapshot("approved")),
    )
    app.state.incident_workflow_service = service
    try:
        created = await client.post(
            "/api/v1/incidents",
            json={
                "incident_id": "INC-HTTP",
                "video_uri": "data_mock/front_camera.mp4",
                "analysis_prompt": "Analyze",
            },
        )
        fetched = await client.get("/api/v1/incidents/INC-HTTP")
        approved = await client.post(
            "/api/v1/incidents/INC-HTTP/review",
            json={"action": "approve", "reviewer": "reviewer@example.com"},
        )
    finally:
        del app.state.incident_workflow_service

    assert created.status_code == 202
    assert fetched.status_code == 200
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert "remote_media_handles" not in created.text
    assert "prompt" not in created.text


@pytest.mark.asyncio
async def test_incident_api_maps_safe_domain_errors(client) -> None:
    service = SimpleNamespace(
        create=AsyncMock(),
        get=AsyncMock(side_effect=WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")),
        review=AsyncMock(),
    )
    app.state.incident_workflow_service = service
    try:
        response = await client.get("/api/v1/incidents/missing")
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "INCIDENT_NOT_FOUND", "message": "incident does not exist"}}


@pytest.mark.asyncio
async def test_incident_api_maps_duplicate_create_to_conflict(client) -> None:
    service = SimpleNamespace(
        create=AsyncMock(side_effect=WorkflowError("INCIDENT_ALREADY_EXISTS", "duplicate")),
        get=AsyncMock(),
        review=AsyncMock(),
    )
    app.state.incident_workflow_service = service
    try:
        response = await client.post(
            "/api/v1/incidents",
            json={
                "incident_id": "INC-HTTP",
                "video_uri": "video.mp4",
                "analysis_prompt": "Analyze",
            },
        )
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INCIDENT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_incident_api_returns_503_without_bootstrapped_service(client) -> None:
    response = await client.get("/api/v1/incidents/missing")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "WORKFLOW_SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_incident_api_rejects_immutable_report_edit(client) -> None:
    service = SimpleNamespace(create=AsyncMock(), get=AsyncMock(), review=AsyncMock())
    app.state.incident_workflow_service = service
    try:
        response = await client.post(
            "/api/v1/incidents/INC-HTTP/review",
            json={
                "action": "edit",
                "reviewer": "reviewer",
                "edits": {"incident_window": "tampered"},
            },
        )
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 422
    service.review.assert_not_awaited()


@pytest.mark.asyncio
async def test_incident_api_hides_unexpected_error_details(client) -> None:
    service = SimpleNamespace(
        create=AsyncMock(),
        get=AsyncMock(side_effect=RuntimeError("secret-token-and-stack")),
        review=AsyncMock(),
    )
    app.state.incident_workflow_service = service
    try:
        response = await client.get("/api/v1/incidents/INC-HTTP")
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 500
    assert "secret-token-and-stack" not in response.text
    assert response.json()["detail"]["code"] == "INCIDENT_WORKFLOW_FAILED"


@pytest.mark.asyncio
async def test_incident_api_rejects_whitespace_only_identifiers(client) -> None:
    service = SimpleNamespace(create=AsyncMock(), get=AsyncMock(), review=AsyncMock())
    app.state.incident_workflow_service = service
    try:
        response = await client.post(
            "/api/v1/incidents",
            json={"incident_id": "   ", "video_uri": "video.mp4", "analysis_prompt": "Analyze"},
        )
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 422
    service.create.assert_not_awaited()
