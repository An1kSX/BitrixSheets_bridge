from __future__ import annotations

from typing import Any, Sequence


class TaskManagerError(Exception):
    pass


class TaskNotFoundError(TaskManagerError):
    pass


class TaskConflictError(TaskManagerError):
    pass


def raise_on_transition_error(response: Sequence[Any], task_id: str) -> None:
    marker = response[0]
    if marker == "missing":
        raise TaskNotFoundError(task_id)
    if marker in {"conflict", "owner_mismatch"}:
        raise TaskConflictError(f"{task_id}: {marker} ({response[1]})")
