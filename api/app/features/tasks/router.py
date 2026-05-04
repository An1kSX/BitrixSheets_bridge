from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.infra.redis import RedisTaskManager, TaskConflictError, TaskNotFoundError, TaskStatus, redis_connection

from .schemas import (
    BridgeTaskKind,
    TaskCancelRequest,
    TaskClaimRequest,
    TaskClaimResponse,
    TaskCompleteRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskFailRequest,
    TaskHeartbeatRequest,
    TaskListResponse,
    TaskRecoverRequest,
    TaskRecoverResponse,
    TaskResponse,
    TaskStatsResponse,
)


router = APIRouter(prefix="/tasks", tags=["Задачи"])
task_manager = RedisTaskManager(redis_connection)


def get_task_manager() -> RedisTaskManager:
    return task_manager


@router.post(
    "",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Создать фоновую задачу",
    description=(
        "Ставит задачу моста Google Sheets <-> Bitrix в Redis-очередь. "
        "Поддерживает отложенный запуск, приоритет, ограничение попыток и ключ идемпотентности."
    ),
)
async def create_task(
    body: TaskCreateRequest,
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    kind = body.kind.value if isinstance(body.kind, BridgeTaskKind) else body.kind
    task, created = await manager.enqueue(
        kind=kind,
        payload=body.payload,
        priority=body.priority,
        scheduled_for=body.scheduled_for,
        delay_seconds=body.delay_seconds,
        max_attempts=body.max_attempts,
        idempotency_key=body.idempotency_key,
        tags=body.tags,
    )
    return {"created": created, **task}


@router.get(
    "",
    response_model=TaskListResponse,
    summary="Получить список задач",
    description="Возвращает задачи из Redis по выбранному статусу с простой пагинацией.",
)
async def list_tasks(
    status_filter: TaskStatus = Query(
        default=TaskStatus.QUEUED,
        alias="status",
        description="Статус задач для выборки.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Максимальное количество задач в ответе."),
    offset: int = Query(default=0, ge=0, description="Смещение от начала списка задач."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    tasks = await manager.list_tasks(status=status_filter.value, limit=limit, offset=offset)
    return {"items": tasks}


@router.get(
    "/stats",
    response_model=TaskStatsResponse,
    summary="Получить статистику очереди",
    description="Возвращает количество задач по статусам и число задач, готовых к выдаче воркерам.",
)
async def get_task_stats(
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    return await manager.stats()


@router.post(
    "/claim",
    response_model=TaskClaimResponse,
    summary="Забрать задачи в работу",
    description=(
        "Атомарно выдает воркеру готовые задачи и ставит lease. "
        "Если воркер не продлит lease через heartbeat, задача будет восстановлена для повторной обработки."
    ),
)
async def claim_tasks(
    body: TaskClaimRequest,
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    tasks = await manager.claim(
        worker_id=body.worker_id,
        limit=body.limit,
        lease_seconds=body.lease_seconds,
    )
    return {"items": tasks}


@router.post(
    "/recover",
    response_model=TaskRecoverResponse,
    summary="Восстановить зависшие задачи",
    description=(
        "Находит running-задачи с истекшим lease и возвращает их в retry "
        "или переводит в failed, если попытки исчерпаны."
    ),
)
async def recover_expired_tasks(
    body: TaskRecoverRequest,
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    return await manager.recover_expired(limit=body.limit)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Получить задачу",
    description="Возвращает сохраненное состояние задачи по ее идентификатору.",
    responses={
        status.HTTP_404_NOT_FOUND:{
            "description": "Задача не найдена."
            }
        },
)
async def get_task(
    task_id: str = Path(..., description="Идентификатор задачи."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    task = await manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена.")
    
    return task


@router.post(
    "/{task_id}/heartbeat",
    response_model=TaskResponse,
    summary="Продлить lease задачи",
    description="Продлевает lease running-задачи, которую сейчас обрабатывает указанный воркер.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Задача не найдена."
            },
        status.HTTP_409_CONFLICT: {
            "description": "Задача уже не находится в ожидаемом состоянии."
            },
    },
)
async def heartbeat_task(
    body: TaskHeartbeatRequest,
    task_id: str = Path(..., description="Идентификатор задачи."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    try:
        return await manager.heartbeat(
            task_id=task_id,
            worker_id=body.worker_id,
            lease_seconds=body.lease_seconds,
        )
    
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена.") from exc
    
    except TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{task_id}/complete",
    response_model=TaskResponse,
    summary="Завершить задачу успешно",
    description="Переводит running-задачу в succeeded и сохраняет результат обработки.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Задача не найдена."
            },
        status.HTTP_409_CONFLICT: {
            "description": "Задача уже не находится в ожидаемом состоянии."
            },
    },
)
async def complete_task(
    body: TaskCompleteRequest,
    task_id: str = Path(..., description="Идентификатор задачи."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    try:
        return await manager.complete(task_id=task_id, worker_id=body.worker_id, result=body.result)
    
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена.") from exc
    
    except TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{task_id}/fail",
    response_model=TaskResponse,
    summary="Завершить задачу ошибкой",
    description=(
        "Фиксирует ошибку обработки. Если задача retryable и попытки не исчерпаны, "
        "она вернется в retry; иначе перейдет в failed."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Задача не найдена."
            },
        status.HTTP_409_CONFLICT: {
            "description": "Задача уже не находится в ожидаемом состоянии."
            },
    },
)
async def fail_task(
    body: TaskFailRequest,
    task_id: str = Path(..., description="Идентификатор задачи."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    try:
        return await manager.fail(
            task_id=task_id,
            worker_id=body.worker_id,
            error=body.error,
            retryable=body.retryable,
            retry_delay_seconds=body.retry_delay_seconds,
        )
    
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена.") from exc
    
    except TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{task_id}/cancel",
    response_model=TaskResponse,
    summary="Отменить задачу",
    description=(
        "Отменяет задачу. Для running-задачи без force выставляет запрос на отмену, "
        "а с force сразу переводит задачу в cancelled."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Задача не найдена."
            },
        status.HTTP_409_CONFLICT: {
            "description": "Задача уже не находится в ожидаемом состоянии."
            },
    },
)
async def cancel_task(
    body: TaskCancelRequest,
    task_id: str = Path(..., description="Идентификатор задачи."),
    manager: RedisTaskManager = Depends(get_task_manager),
) -> Dict[str, Any]:
    try:
        return await manager.cancel(task_id=task_id, reason=body.reason, force=body.force)
    
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена.") from exc
    
    except TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
