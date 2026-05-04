from __future__ import annotations

import secrets

from fastapi import HTTPException, Query, status

from app.core.config import settings


def require_api_token(
    token: str = Query(
        ...,
        description="Обязательный API-токен для доступа к endpoint.",
    ),
) -> None:
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Некорректный API-токен.",
        )
