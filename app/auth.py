"""Simple bearer-token auth for non-health endpoints."""

import re
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    # Require a random URL-safe token, not an example placeholder.
    token = settings.api_token
    if (
        re.fullmatch(r"[A-Za-z0-9_-]{32,}", token) is None
        or len(set(token)) < 8
        or any(marker in token.lower() for marker in ("change", "replace", "example", "placeholder"))
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCAL_LLM_API_TOKEN must be configured with a strong random token",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.api_token.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
