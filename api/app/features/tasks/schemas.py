from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator


class BridgeTaskKind(str, Enum):
    SHEETS_TO_BITRIX_SYNC = "bridge.sheets_to_bitrix.sync"
    BITRIX_TO_SHEETS_SYNC = "bridge.bitrix_to_sheets.sync"
    FULL_RECONCILE = "bridge.reconcile.full"
    BITRIX_WEBHOOK = "bridge.bitrix.webhook"
    SHEETS_POLL = "bridge.sheets.poll"
    BITRIX_BATCH = "bridge.bitrix.batch"


class TaskCreateRequest(BaseModel):
    kind: Union[BridgeTaskKind, str] = Field(
        ...,
        description="Тип задачи моста, например bridge.sheets_to_bitrix.sync.",
    )
    payload: Dict[str, Any] = Field(default_factory=dict, description="Данные задачи для обработчика.")
    priority: int = Field(default=50, ge=0, le=100, description="Приоритет задачи: 100 - самый высокий.")
    scheduled_for: Optional[datetime] = Field(default=None, description="Точное время запуска задачи.")
    delay_seconds: Optional[int] = Field(default=None, ge=0, description="Задержка запуска в секундах.")
    max_attempts: Optional[int] = Field(default=None, ge=1, le=100, description="Максимальное число попыток.")
    idempotency_key: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Ключ идемпотентности для защиты от дублирования задачи.",
    )
    tags: List[str] = Field(default_factory=list, description="Свободные метки для поиска и диагностики.")

    @model_validator(mode="after")
    def validate_schedule(self) -> "TaskCreateRequest":
        if self.scheduled_for is not None and self.delay_seconds is not None:
            raise ValueError("Используйте либо scheduled_for, либо delay_seconds, но не оба поля одновременно.")
        return self


class TaskClaimRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200, description="Идентификатор воркера.")
    limit: int = Field(default=1, ge=1, le=100, description="Сколько задач забрать за один запрос.")
    lease_seconds: Optional[int] = Field(default=None, ge=5, le=86400, description="Длительность lease в секундах.")


class TaskHeartbeatRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200, description="Идентификатор воркера.")
    lease_seconds: Optional[int] = Field(default=None, ge=5, le=86400, description="Новая длительность lease в секундах.")


class TaskCompleteRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200, description="Идентификатор воркера.")
    result: Dict[str, Any] = Field(default_factory=dict, description="Результат успешной обработки задачи.")


class TaskFailRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=200, description="Идентификатор воркера.")
    error: str = Field(..., min_length=1, max_length=4000, description="Текст ошибки обработки.")
    retryable: bool = Field(default=True, description="Можно ли повторить задачу после ошибки.")
    retry_delay_seconds: Optional[int] = Field(
        default=None,
        ge=0,
        le=86400,
        description="Явная задержка перед повторной попыткой. Если не задана, используется backoff.",
    )


class TaskCancelRequest(BaseModel):
    reason: str = Field(default="", max_length=1000, description="Причина отмены.")
    force: bool = Field(default=False, description="Принудительно отменить даже running-задачу.")


class TaskRecoverRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000, description="Максимум зависших задач для восстановления.")


class TaskResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    payload: Dict[str, Any]
    priority: int
    max_attempts: int
    attempts: int
    created_at: Optional[str]
    updated_at: Optional[str]
    scheduled_for: Optional[str]
    ready_at_ms: int
    claimed_at: Optional[str]
    finished_at: Optional[str]
    lease_expires_at: Optional[str]
    lock_owner: Optional[str]
    idempotency_key: Optional[str]
    tags: List[str]
    result: Optional[Dict[str, Any]]
    last_error: Optional[str]
    cancel_requested: bool
    cancel_reason: Optional[str]


class TaskCreateResponse(TaskResponse):
    created: bool


class TaskListResponse(BaseModel):
    items: List[TaskResponse]


class TaskClaimResponse(BaseModel):
    items: List[TaskResponse]


class TaskStatsResponse(BaseModel):
    queued: int = 0
    scheduled: int = 0
    running: int = 0
    retrying: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    ready: int = 0


class TaskRecoverResponse(BaseModel):
    requeued: int
    failed: int
