from __future__ import annotations

from typing import Optional

from redis.asyncio import ConnectionPool, Redis


class RedisClient:
    def __init__(
        self,
        redis_url: str,
        max_connections: Optional[int] = None,
    ):
        pool_options = {
            "decode_responses": True,
            "health_check_interval": 30,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        }
        if max_connections is not None:
            pool_options["max_connections"] = max_connections

        self.pool = ConnectionPool.from_url(
            redis_url,
            **pool_options,
        )
        self.redis = Redis(connection_pool=self.pool)

    async def get_redis(self) -> Redis:
        return self.redis

    async def close(self) -> None:
        await self.redis.aclose(close_connection_pool=True)
