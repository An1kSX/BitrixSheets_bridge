from __future__ import annotations

from typing import Dict, Union

from fastapi import APIRouter, Response, status

from app.infra.redis import RedisTaskManager, redis_connection


router = APIRouter(prefix="/app", tags=["Приложение"])
task_manager = RedisTaskManager(redis_connection)


@router.get(
    "/health",
    summary="Проверить состояние приложения",
    description="Проверяет доступность API и соединение с Redis.",
)
async def health(response: Response) -> Dict[str, Union[str, bool]]:
    redis_ok = False
    try:
        redis_ok = await task_manager.ping()
    except Exception:
        redis_ok = False

    if not redis_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
    }
