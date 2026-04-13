from __future__ import annotations

from fastapi import APIRouter

from api.schemas.ingest_tasks import IngestTaskOut
from api.services.ingest_tasks_service import IngestTasksService

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
