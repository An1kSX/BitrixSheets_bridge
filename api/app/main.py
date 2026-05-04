from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.security import require_api_token
from app.features.app import router as app_router
from app.features.tasks import router as tasks_router
from app.infra.redis import close_redis, redis_connection


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with AsyncExitStack() as stack:
        stack.push_async_callback(close_redis)
        await redis_connection.ping()
        yield


def create_app() -> FastAPI:
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

    auth_dependencies = [Depends(require_api_token)]

    app.include_router(app_router, dependencies=auth_dependencies)
    app.include_router(tasks_router, prefix="/app", dependencies=auth_dependencies)

    return app


app = create_app()
