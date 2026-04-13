from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from grag.storage import IngestTaskRecord
from grag.storage.storage_impl import DataClientGraphStorage

from .graph_builder import GraphBuilder


class AsyncGraphBuildService:
    _instance: "AsyncGraphBuildService | None" = None
    _lock = Lock()

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="grag-graph-build")
        self._storage = DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert")

    @classmethod
    def instance(cls) -> "AsyncGraphBuildService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def submit(
        self,
        *,
        text: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ) -> IngestTaskRecord:
        now = self._now()
        task = IngestTaskRecord(
            task_id=uuid4().hex,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status="pending",
            stage="queued",
            message="graph build queued",
            created_at=now,
            updated_at=now,
        )
        self._storage.upsert_ingest_task(task=task)
        self._executor.submit(
            self._run_task,
            task_id=task.task_id,
            created_at=task.created_at,
            text=text,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
        )
        return task

    def _update_task(
        self,
        *,
        task_id: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        status: str,
        stage: str,
        message: str,
        created_at: str,
    ) -> None:
        self._storage.upsert_ingest_task(
            task=IngestTaskRecord(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status=status,
                stage=stage,
                message=message,
                created_at=created_at,
                updated_at=self._now(),
            )
        )

    def _run_task(
        self,
        *,
        task_id: str,
        created_at: str,
        text: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ) -> None:
        self._update_task(
            task_id=task_id,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status="running",
            stage="graph_construction",
            message="graph construction in progress",
            created_at=created_at,
        )
        try:
            builder = GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))
            builder.build_graph_and_save(
                text=text,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
            )
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status="completed",
                stage="done",
                message="graph construction completed",
                created_at=created_at,
            )
        except Exception as e:
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status="failed",
                stage="graph_construction",
                message=f"{type(e).__name__}: {e}",
                created_at=created_at,
            )
