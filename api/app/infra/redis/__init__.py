from app.core.config import settings
from redis.asyncio import Redis

from .client import RedisClient
from .errors import TaskConflictError, TaskManagerError, TaskNotFoundError
from .models import TaskData, TaskStatus
from .task_manager import RedisTaskManager


redis_client = RedisClient(
    settings.redis_url,
    max_connections=settings.redis_pool_max_connections,
)
redis_connection = redis_client.redis


async def get_redis() -> Redis:
    return await redis_client.get_redis()


async def close_redis() -> None:
    await redis_client.close()


__all__ = [
    "close_redis",
    "get_redis",
    "redis_client",
    "redis_connection",
    "RedisClient",
    "RedisTaskManager",
    "TaskConflictError",
    "TaskData",
    "TaskManagerError",
    "TaskNotFoundError",
    "TaskStatus",
]
