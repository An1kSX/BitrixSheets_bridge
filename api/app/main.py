from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, Union

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.features.tasks import router as tasks_router
from app.infra.redis import RedisTaskManager, close_redis, redis_connection


task_manager = RedisTaskManager(redis_connection)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await redis_connection.ping()
    yield
    await close_redis()


app = FastAPI(
    title="BitrixSheets Bridge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.origin_regex,
    allow_credentials=settings.allow_credentials,
    allow_methods=settings.allow_methods,
    allow_headers=settings.allow_headers,
)

app.include_router(tasks_router, prefix="/app")


@app.get("/app/health")
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
