from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


QUEUE_SCORE_FACTOR = 1000
MAX_PRIORITY = 100


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_ready_at(
    now: datetime,
    *,
    scheduled_for: Optional[datetime],
    delay_seconds: Optional[int],
) -> datetime:
    if scheduled_for is not None:
        return ensure_utc(scheduled_for)
    if delay_seconds is not None and delay_seconds > 0:
        return now + timedelta(seconds=delay_seconds)
    return now


def to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def to_iso(value: datetime) -> str:
    return ensure_utc(value).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def clamp_priority(priority: int) -> int:
    return max(0, min(MAX_PRIORITY, priority))


def queue_score(ready_at_ms: int, priority: int) -> int:
    return ready_at_ms * QUEUE_SCORE_FACTOR + (MAX_PRIORITY - clamp_priority(priority))


def retry_delay_seconds(*, attempts: int, base_seconds: int, max_seconds: int) -> int:
    return min(max_seconds, base_seconds * (2 ** max(attempts - 1, 0)))


def decode_task(raw: Dict[str, str]) -> Dict[str, Any]:
    return {
        "task_id": raw["task_id"],
        "kind": raw["kind"],
        "status": raw["status"],
        "payload": loads(raw.get("payload", ""), {}),
        "priority": int(raw.get("priority") or 0),
        "max_attempts": int(raw.get("max_attempts") or 1),
        "attempts": int(raw.get("attempts") or 0),
        "created_at": raw.get("created_at") or None,
        "updated_at": raw.get("updated_at") or None,
        "scheduled_for": raw.get("scheduled_for") or None,
        "ready_at_ms": int(raw.get("ready_at_ms") or 0),
        "claimed_at": raw.get("claimed_at") or None,
        "finished_at": raw.get("finished_at") or None,
        "lease_expires_at": raw.get("lease_expires_at") or None,
        "lock_owner": raw.get("lock_owner") or None,
        "idempotency_key": raw.get("idempotency_key") or None,
        "tags": loads(raw.get("tags", ""), []),
        "result": loads(raw.get("result", ""), None),
        "last_error": raw.get("last_error") or None,
        "cancel_requested": raw.get("cancel_requested") == "true",
        "cancel_reason": raw.get("cancel_reason") or None,
    }
