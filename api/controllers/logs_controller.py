from __future__ import annotations

from fastapi import APIRouter

from api.services.logs_service import LogsService

router = APIRouter()


@router.get("/tail")
def tail_logs(
    lines: int = 200,
    contains: str | None = None,
    group_id: str | None = None,
    doc_id: str | None = None,
    task_id: str | None = None,
) -> dict:
    svc = LogsService()
    return svc.tail(
        lines=lines,
        contains=contains,
        group_id=group_id,
        doc_id=doc_id,
        task_id=task_id,
    )
