from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from app.core.config import settings
from app.core.logger import ModuleLogger
from app.infra.redis import RedisTaskManager


TaskResult = Optional[Dict[str, Any]]
TaskHandler = Callable[[Dict[str, Any]], Union[TaskResult, Awaitable[TaskResult]]]


class NonRetryableTaskError(Exception):
    pass


logger = ModuleLogger(
    module_name=__name__,
    to_console=settings.to_console,
    to_file=settings.to_file,
    log_level=settings.log_level,
).get_logger()


class BridgeTaskWorker:
    def __init__(
        self,
        manager: RedisTaskManager,
        handlers: Dict[str, TaskHandler],
        *,
        worker_id: Optional[str] = None,
        batch_size: int = 5,
        poll_interval_seconds: float = 1.0,
        lease_seconds: Optional[int] = None,
    ) -> None:
        self.manager = manager
        self.handlers = handlers
        self.worker_id = worker_id or f"bridge-worker-{uuid.uuid4()}"
        self.batch_size = batch_size
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds or settings.task_default_lease_seconds

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        while stop_event is None or not stop_event.is_set():
            processed = await self.run_once()
            if processed == 0:
                await asyncio.sleep(self.poll_interval_seconds)

    async def run_once(self) -> int:
        tasks = await self.manager.claim(
            worker_id=self.worker_id,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        if not tasks:
            return 0

        await asyncio.gather(*(self._run_task(task) for task in tasks))
        return len(tasks)

    async def _run_task(self, task: Dict[str, Any]) -> None:
        task_id = task["task_id"]
        kind = task["kind"]
        handler = self.handlers.get(kind)

        if handler is None:
            await self.manager.fail(
                task_id=task_id,
                worker_id=self.worker_id,
                error=f"No handler registered for task kind: {kind}",
                retryable=False,
            )
            return

        heartbeat = asyncio.create_task(self._heartbeat(task_id))
        try:
            result = handler(task)
            if inspect.isawaitable(result):
                result = await result
            await self.manager.complete(
                task_id=task_id,
                worker_id=self.worker_id,
                result=result or {},
            )
        except NonRetryableTaskError as exc:
            logger.exception("Task %s failed without retry.", task_id)
            await self.manager.fail(
                task_id=task_id,
                worker_id=self.worker_id,
                error=str(exc),
                retryable=False,
            )
        except Exception as exc:
            logger.exception("Task %s failed.", task_id)
            await self.manager.fail(
                task_id=task_id,
                worker_id=self.worker_id,
                error=str(exc),
                retryable=True,
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("Heartbeat task for %s stopped with an error.", task_id, exc_info=True)

    async def _heartbeat(self, task_id: str) -> None:
        interval = max(1, self.lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            await self.manager.heartbeat(
                task_id=task_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
