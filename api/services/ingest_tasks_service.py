from __future__ import annotations

from grag.data_client import get_data_manager
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import IngestTaskRecord


class IngestTasksService:
    def __init__(self) -> None:
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())

    def get_task(self, *, task_id: str) -> IngestTaskRecord | None:
        return self._pg.get_ingest_task(task_id=task_id)

    def list_tasks(
        self,
        *,
        group_id: str | None = None,
        doc_id: str | None = None,
        limit: int = 100,
    ) -> list[IngestTaskRecord]:
        return self._pg.list_ingest_tasks(group_id=group_id, doc_id=doc_id, limit=int(limit))
