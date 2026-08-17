from secrets import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, status

from src.config import get_settings


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Require the configured service API key for protected API routes.

    This is a small deployment guard for the current single-service API. A
    production identity provider/OIDC integration can replace this dependency
    without changing the route handlers.
    """
    configured_key = get_settings().security_api_key.strip()
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )

    if not x_api_key or not compare_digest(x_api_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
