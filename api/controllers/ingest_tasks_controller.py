from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas.ingest_tasks import (
    IngestTaskCancelOut,
    IngestTaskClearIn,
    IngestTaskClearOut,
    IngestTaskDeleteOut,
    IngestTaskOut,
    IngestTaskTraceOut,
)
from api.services.trace_service import TraceService
from api.services.ingest_tasks_service import IngestTasksService
from grag.graph_construction.async_graph_service import AsyncGraphBuildService

router = APIRouter()


@router.get("")
def list_ingest_tasks(
    group_id: str | None = None,
    doc_id: str | None = None,
    limit: int = 100,
) -> list[IngestTaskOut]:
    svc = IngestTasksService()
    tasks = svc.list_tasks(group_id=group_id, doc_id=doc_id, limit=limit)
    return [IngestTaskOut.from_record(t) for t in tasks]


@router.get("/{task_id}")
def get_ingest_task(task_id: str) -> IngestTaskOut | None:
    svc = IngestTasksService()
    task = svc.get_task(task_id=task_id)
    return IngestTaskOut.from_record(task) if task is not None else None


@router.get("/{task_id}/trace")
def get_ingest_task_trace(task_id: str) -> IngestTaskTraceOut:
    svc = IngestTasksService()
    task = svc.get_task(task_id=task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    timeline = TraceService().get_ingest_task_trace(task_id=task_id)
    return IngestTaskTraceOut(task=IngestTaskOut.from_record(task), timeline=timeline)


@router.delete("/{task_id}")
def delete_ingest_task(task_id: str) -> IngestTaskDeleteOut:
    try:
        ok = AsyncGraphBuildService.instance().delete_task_record(task_id=task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IngestTaskDeleteOut(ok=ok, task_id=str(task_id))


@router.post("/{task_id}/cancel")
def cancel_ingest_task(task_id: str) -> IngestTaskCancelOut:
    try:
        task = AsyncGraphBuildService.instance().request_cancel(task_id=task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IngestTaskCancelOut(ok=True, task_id=str(task_id), status=str(task.status))


@router.post("/{task_id}/resume")
def resume_ingest_task(task_id: str) -> IngestTaskOut:
    try:
        task = AsyncGraphBuildService.instance().resume_task(task_id=task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IngestTaskOut.from_record(task)


@router.post("/clear")
def clear_ingest_tasks(payload: IngestTaskClearIn) -> IngestTaskClearOut:
    try:
        deleted = AsyncGraphBuildService.instance().clear_task_records(
            group_id=payload.group_id,
            doc_id=payload.doc_id,
            statuses=payload.statuses or [],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IngestTaskClearOut(ok=True, deleted=deleted)
