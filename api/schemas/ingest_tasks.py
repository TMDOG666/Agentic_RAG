from __future__ import annotations

from pydantic import BaseModel

from grag.storage.types import IngestTaskRecord


class IngestTaskOut(BaseModel):
    task_id: str
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    status: str
    stage: str
    message: str
    created_at: str
    updated_at: str

    @staticmethod
    def from_record(task: IngestTaskRecord) -> "IngestTaskOut":
        return IngestTaskOut(
            task_id=str(task.task_id),
            group_id=str(task.group_id),
            doc_id=str(task.doc_id),
            doc_name=str(task.doc_name),
            doc_time=str(task.doc_time),
            status=str(task.status),
            stage=str(task.stage),
            message=str(task.message),
            created_at=str(task.created_at),
            updated_at=str(task.updated_at),
        )


class IngestTaskDeleteOut(BaseModel):
    ok: bool
    task_id: str


class IngestTaskClearIn(BaseModel):
    group_id: str | None = None
    doc_id: str | None = None
    statuses: list[str] | None = None


class IngestTaskClearOut(BaseModel):
    ok: bool
    deleted: int
