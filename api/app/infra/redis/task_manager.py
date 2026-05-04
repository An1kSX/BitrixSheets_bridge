from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from redis.asyncio import Redis

from app.core.config import settings

from .codec import (
    QUEUE_SCORE_FACTOR,
    clamp_priority,
    decode_task,
    dumps,
    queue_score,
    resolve_ready_at,
    retry_delay_seconds as calculate_retry_delay_seconds,
    to_iso,
    to_ms,
    utc_now,
)
from .errors import TaskNotFoundError, raise_on_transition_error
from .keyspace import TaskKeyspace
from .models import TaskData, TaskStatus
from .scripts import (
    CANCEL_SCRIPT,
    CLAIM_SCRIPT,
    COMPLETE_SCRIPT,
    ENQUEUE_SCRIPT,
    FAIL_SCRIPT,
    HEARTBEAT_SCRIPT,
    RECOVER_EXPIRED_SCRIPT,
)


class RedisTaskManager:
    def __init__(
        self,
        redis: Redis,
        *,
        prefix: Optional[str] = None,
        default_max_attempts: Optional[int] = None,
        default_lease_seconds: Optional[int] = None,
        retry_base_seconds: Optional[int] = None,
        retry_max_seconds: Optional[int] = None,
        idempotency_ttl_seconds: Optional[int] = None,
    ) -> None:
        self.redis = redis
        self.prefix = prefix or settings.task_queue_prefix
        self.keys = TaskKeyspace(self.prefix)
        self.default_max_attempts = default_max_attempts or settings.task_default_max_attempts
        self.default_lease_seconds = default_lease_seconds or settings.task_default_lease_seconds
        self.retry_base_seconds = retry_base_seconds or settings.task_retry_base_seconds
        self.retry_max_seconds = retry_max_seconds or settings.task_retry_max_seconds
        self.idempotency_ttl_seconds = idempotency_ttl_seconds or settings.task_idempotency_ttl_seconds

    async def enqueue(
        self,
        *,
        kind: str,
        payload: Dict[str, Any],
        priority: int = 50,
        scheduled_for: Optional[datetime] = None,
        delay_seconds: Optional[int] = None,
        max_attempts: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Tuple[TaskData, bool]:
        now = utc_now()
        now_ms = to_ms(now)
        ready_at = resolve_ready_at(now, scheduled_for=scheduled_for, delay_seconds=delay_seconds)
        ready_at_ms = to_ms(ready_at)
        status = TaskStatus.SCHEDULED.value if ready_at_ms > now_ms else TaskStatus.QUEUED.value
        task_id = str(uuid.uuid4())
        priority = clamp_priority(priority)
        attempts_limit = max(1, max_attempts or self.default_max_attempts)
        tag_list = list(tags or [])

        fields = {
            "task_id": task_id,
            "kind": kind,
            "status": status,
            "payload": dumps(payload),
            "priority": str(priority),
            "max_attempts": str(attempts_limit),
            "attempts": "0",
            "created_at": to_iso(now),
            "updated_at": to_iso(now),
            "ready_at_ms": str(ready_at_ms),
            "scheduled_for": to_iso(ready_at),
            "claimed_at": "",
            "finished_at": "",
            "lease_expires_at": "",
            "lease_expires_at_ms": "",
            "lock_owner": "",
            "idempotency_key": idempotency_key or "",
            "tags": dumps(tag_list),
            "result": "",
            "last_error": "",
            "cancel_requested": "false",
            "cancel_reason": "",
        }
        flat_fields = [item for pair in fields.items() for item in pair]
        has_idempotency = "1" if idempotency_key else "0"
        idem_key = self.keys.idempotency(idempotency_key) if idempotency_key else self.keys.noop_idempotency()

        response = await self.redis.eval(
            ENQUEUE_SCRIPT,
            5,
            self.keys.task(task_id),
            self.keys.queue(),
            idem_key,
            self.keys.status(status),
            self.keys.kind(kind),
            task_id,
            status,
            str(queue_score(ready_at_ms, priority)),
            str(now_ms),
            has_idempotency,
            str(self.idempotency_ttl_seconds),
            *flat_fields,
        )
        marker, stored_task_id = response[0], response[1]
        task = await self.get_task(stored_task_id)
        if task is None:
            raise TaskNotFoundError(stored_task_id)
        return task, marker == "created"

    async def get_task(self, task_id: str) -> Optional[TaskData]:
        raw = await self.redis.hgetall(self.keys.task(task_id))
        if not raw:
            return None
        return decode_task(raw)

    async def list_tasks(
        self,
        *,
        status: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[TaskData]:
        task_ids = await self.redis.zrevrange(self.keys.status(status), offset, offset + limit - 1)
        tasks = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task is not None:
                tasks.append(task)
        return tasks

    async def claim(
        self,
        *,
        worker_id: str,
        limit: int = 1,
        lease_seconds: Optional[int] = None,
        recover_expired_first: bool = True,
    ) -> List[TaskData]:
        if recover_expired_first:
            await self.recover_expired(limit=100)

        now = utc_now()
        lease_seconds = lease_seconds or self.default_lease_seconds
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        task_ids = await self.redis.eval(
            CLAIM_SCRIPT,
            3,
            self.keys.queue(),
            self.keys.running(),
            self.keys.status(TaskStatus.RUNNING.value),
            str(queue_score(to_ms(now), 0)),
            str(max(1, limit)),
            str(to_ms(now)),
            str(to_ms(lease_expires_at)),
            worker_id,
            to_iso(lease_expires_at),
            to_iso(now),
            self.prefix,
        )
        tasks = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task is not None:
                tasks.append(task)
        return tasks

    async def heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_seconds: Optional[int] = None,
    ) -> TaskData:
        now = utc_now()
        lease_seconds = lease_seconds or self.default_lease_seconds
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        response = await self.redis.eval(
            HEARTBEAT_SCRIPT,
            2,
            self.keys.task(task_id),
            self.keys.running(),
            task_id,
            worker_id,
            to_iso(lease_expires_at),
            str(to_ms(lease_expires_at)),
            to_iso(now),
        )
        raise_on_transition_error(response, task_id)
        return await self._require_task(task_id)

    async def complete(
        self,
        *,
        task_id: str,
        worker_id: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> TaskData:
        now = utc_now()
        response = await self.redis.eval(
            COMPLETE_SCRIPT,
            4,
            self.keys.task(task_id),
            self.keys.running(),
            self.keys.status(TaskStatus.RUNNING.value),
            self.keys.status(TaskStatus.SUCCEEDED.value),
            task_id,
            worker_id,
            to_iso(now),
            str(to_ms(now)),
            dumps(result or {}),
        )
        raise_on_transition_error(response, task_id)
        return await self._require_task(task_id)

    async def fail(
        self,
        *,
        task_id: str,
        worker_id: str,
        error: str,
        retryable: bool = True,
        retry_delay_seconds: Optional[int] = None,
    ) -> TaskData:
        now = utc_now()
        task = await self._require_task(task_id)
        delay_seconds = retry_delay_seconds
        if delay_seconds is None:
            delay_seconds = calculate_retry_delay_seconds(
                attempts=int(task.get("attempts", 1)),
                base_seconds=self.retry_base_seconds,
                max_seconds=self.retry_max_seconds,
            )

        ready_at = now + timedelta(seconds=max(0, delay_seconds))
        priority = clamp_priority(int(task.get("priority", 50)))
        response = await self.redis.eval(
            FAIL_SCRIPT,
            6,
            self.keys.task(task_id),
            self.keys.running(),
            self.keys.status(TaskStatus.RUNNING.value),
            self.keys.queue(),
            self.keys.status(TaskStatus.RETRYING.value),
            self.keys.status(TaskStatus.FAILED.value),
            task_id,
            worker_id,
            to_iso(now),
            str(to_ms(now)),
            error[:4000],
            "1" if retryable else "0",
            str(to_ms(ready_at)),
            str(queue_score(to_ms(ready_at), priority)),
        )
        raise_on_transition_error(response, task_id)
        return await self._require_task(task_id)

    async def cancel(
        self,
        *,
        task_id: str,
        reason: str = "",
        force: bool = False,
    ) -> TaskData:
        now = utc_now()
        response = await self.redis.eval(
            CANCEL_SCRIPT,
            4,
            self.keys.task(task_id),
            self.keys.queue(),
            self.keys.running(),
            self.keys.status(TaskStatus.CANCELLED.value),
            task_id,
            "1" if force else "0",
            to_iso(now),
            str(to_ms(now)),
            reason[:1000],
            self.prefix,
        )
        raise_on_transition_error(response, task_id)
        return await self._require_task(task_id)

    async def recover_expired(self, *, limit: int = 100) -> Dict[str, int]:
        now = utc_now()
        response = await self.redis.eval(
            RECOVER_EXPIRED_SCRIPT,
            5,
            self.keys.running(),
            self.keys.status(TaskStatus.RUNNING.value),
            self.keys.queue(),
            self.keys.status(TaskStatus.RETRYING.value),
            self.keys.status(TaskStatus.FAILED.value),
            str(to_ms(now)),
            str(max(1, limit)),
            str(to_ms(now)),
            to_iso(now),
            str(self.retry_base_seconds * 1000),
            str(self.retry_max_seconds * 1000),
            str(QUEUE_SCORE_FACTOR),
            self.prefix,
        )
        return {"requeued": int(response[0]), "failed": int(response[1])}

    async def stats(self) -> Dict[str, int]:
        counts = {
            status.value: int(await self.redis.zcard(self.keys.status(status.value)))
            for status in TaskStatus
        }
        counts["ready"] = int(
            await self.redis.zcount(
                self.keys.queue(),
                "-inf",
                queue_score(to_ms(utc_now()), 0),
            )
        )
        return counts

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def _require_task(self, task_id: str) -> TaskData:
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task
