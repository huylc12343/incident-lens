from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.main import app


AUTH_HEADERS = {"X-API-Key": "test-key"}

# Test marker for the development activity log.

@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "live"


@pytest.mark.asyncio
async def test_live_is_independent_from_workflow_readiness(client):
    assert (await client.get("/live")).status_code == 200
    assert (await client.get("/ready")).status_code == 503


@pytest.mark.asyncio
async def test_ready_checks_initialized_workflow_dependencies(client):
    service = SimpleNamespace(ready=AsyncMock(return_value=None))
    app.state.incident_workflow_service = service
    try:
        response = await client.get("/ready")
    finally:
        del app.state.incident_workflow_service

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    service.ready.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post(
        "/api/v1/chat",
        json={"message": ""},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status", headers=AUTH_HEADERS)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_protected_route_requires_api_key(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 401
