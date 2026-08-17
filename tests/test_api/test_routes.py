import pytest


AUTH_HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


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
