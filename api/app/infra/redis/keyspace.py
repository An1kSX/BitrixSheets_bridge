from __future__ import annotations

import hashlib


class TaskKeyspace:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def task(self, task_id: str) -> str:
        return f"{self.prefix}:task:{task_id}"

    def queue(self) -> str:
        return f"{self.prefix}:index:queue"

    def running(self) -> str:
        return f"{self.prefix}:index:running"

    def status(self, status: str) -> str:
        return f"{self.prefix}:index:status:{status}"

    def kind(self, kind: str) -> str:
        digest = hashlib.sha1(kind.encode("utf-8")).hexdigest()
        return f"{self.prefix}:index:kind:{digest}"

    def idempotency(self, idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"{self.prefix}:idempotency:{digest}"

    def noop_idempotency(self) -> str:
        return f"{self.prefix}:idempotency:_noop"
