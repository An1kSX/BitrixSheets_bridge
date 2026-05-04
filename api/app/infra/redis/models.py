from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class TaskStatus(str, Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TaskData = Dict[str, Any]
