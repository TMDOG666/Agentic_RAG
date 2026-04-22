from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from threading import Lock
from uuid import uuid4

from grag.config import ProviderType, get_config_manager
from grag.storage import IngestTaskRecord
from grag.storage.storage_impl import DataClientGraphStorage

from .graph_builder import GraphBuilder
from .graph_construction_manager import GraphConstructionStreamEvent
from api.services.documents_service import DocumentsService
from api.services.ingest_tasks_service import IngestTasksService


logger = logging.getLogger(__name__)


class AsyncGraphBuildService:
    _instance: "AsyncGraphBuildService | None" = None
    _lock = Lock()

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="grag-graph-build")
        self._storage = DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert")
        self._documents = DocumentsService()
        self._tasks_service = IngestTasksService()
        self._futures: dict[str, object] = {}
        self._task_lock = Lock()

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
        self._submit_future(
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

    def submit_existing(
        self,
        *,
        task_id: str,
        created_at: str,
        text: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        initial_status: str = "pending",
        initial_stage: str = "queued",
        initial_message: str = "graph build resumed",
    ) -> IngestTaskRecord:
        task = IngestTaskRecord(
            task_id=str(task_id),
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status=initial_status,
            stage=initial_stage,
            message=initial_message,
            created_at=created_at,
            updated_at=self._now(),
        )
        self._storage.upsert_ingest_task(task=task)
        self._submit_future(
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

    def _submit_future(self, fn, /, **kwargs) -> None:
        task_id = str(kwargs.get("task_id") or "")
        future = self._executor.submit(fn, **kwargs)
        if not task_id:
            return
        with self._task_lock:
            self._futures[task_id] = future

        def _cleanup(done_future) -> None:
            with self._task_lock:
                current = self._futures.get(task_id)
                if current is done_future:
                    self._futures.pop(task_id, None)

        future.add_done_callback(_cleanup)

    def is_task_active(self, *, task_id: str) -> bool:
        key = str(task_id or "").strip()
        if not key:
            return False
        with self._task_lock:
            future = self._futures.get(key)
        return bool(future is not None and not future.done())

    def delete_task_record(self, *, task_id: str) -> bool:
        if self.is_task_active(task_id=task_id):
            raise RuntimeError("任务仍在运行，不能删除")
        return self._tasks_service.delete_task(task_id=task_id)

    def clear_task_records(
        self,
        *,
        group_id: str | None = None,
        doc_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> int:
        normalized_statuses = [str(s).strip() for s in (statuses or []) if str(s).strip()]
        tasks = self._tasks_service.list_tasks(group_id=group_id, doc_id=doc_id, limit=10000)
        for task in tasks:
            if normalized_statuses and task.status not in normalized_statuses:
                continue
            if self.is_task_active(task_id=task.task_id):
                raise RuntimeError(f"任务仍在运行，不能清除: {task.task_id}")
        return self._tasks_service.clear_tasks(group_id=group_id, doc_id=doc_id, statuses=normalized_statuses)

    def resume_incomplete_tasks(self) -> int:
        recovered = 0
        try:
            get_config_manager().reload_config()
        except Exception as exc:
            logger.warning("Failed to reload config before recovering ingest tasks: %s: %s", type(exc).__name__, exc)
        tasks = self._tasks_service.list_recoverable_tasks(limit=1000)
        for task in tasks:
            try:
                if self.is_task_active(task_id=task.task_id):
                    continue
                text = self._documents.get_document_text(group_id=task.group_id, doc_id=task.doc_id)
                if not str(text or "").strip():
                    self._update_task(
                        task_id=task.task_id,
                        group_id=task.group_id,
                        doc_id=task.doc_id,
                        doc_name=task.doc_name,
                        doc_time=task.doc_time,
                        status="failed",
                        stage=task.stage or "resume",
                        message="resume failed: document text missing",
                        created_at=task.created_at,
                    )
                    continue
                self._documents.update_document_stage(
                    group_id=task.group_id,
                    doc_id=task.doc_id,
                    ingest_stage="graph_retrying",
                    extra_metadata={"graph_resume_task_id": task.task_id},
                )
                self.submit_existing(
                    task_id=task.task_id,
                    created_at=task.created_at,
                    text=text,
                    group_id=task.group_id,
                    doc_id=task.doc_id,
                    doc_name=task.doc_name,
                    doc_time=task.doc_time,
                    initial_status="pending",
                    initial_stage=task.stage or "queued",
                    initial_message=f"task resumed after restart: {task.message}",
                )
                recovered += 1
            except Exception as exc:
                logger.warning("Failed to resume ingest task %s: %s: %s", task.task_id, type(exc).__name__, exc)
        return recovered

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

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
        try:
            manager = get_config_manager()
            if not manager.reload_config():
                raise RuntimeError("reload grag_config.yaml failed")
            settings = manager.get_settings()
            llm_provider_name = str(settings.llm_provider or "").strip()
            llm_provider = manager.get_provider_config(ProviderType.LLM, llm_provider_name)
            logger.info(
                "Ingest task %s runtime config loaded: llm_provider=%s model=%s embedding_provider=%s reranker_provider=%s",
                task_id,
                llm_provider_name or "unknown",
                str(getattr(llm_provider, "model", "") or "").strip() or "unknown",
                str(settings.embedding_provider or "").strip() or "unknown",
                str(settings.reranker_provider or "").strip() or "unknown",
            )
        except Exception as exc:
            logger.warning("Failed to reload config for ingest task %s: %s: %s", task_id, type(exc).__name__, exc)

        def _handle_progress(event: GraphConstructionStreamEvent) -> None:
            stage = event.stage
            message = event.message
            if event.chunk_index is not None and event.total_chunks:
                message = f"{message} ({event.chunk_index + 1}/{event.total_chunks})"
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status="running",
                stage=stage,
                message=message,
                created_at=created_at,
            )

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
        self._documents.update_document_stage(
            group_id=group_id,
            doc_id=doc_id,
            ingest_stage="graph_processing",
        )
        try:
            builder = GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))
            builder.build_graph_and_save(
                text=text,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
                progress_callback=_handle_progress,
                stream_base=False,
            )
            self._documents.update_document_stage(
                group_id=group_id,
                doc_id=doc_id,
                ingest_stage="graph_completed",
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
            progress = self._documents.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
            self._documents.update_document_stage(
                group_id=group_id,
                doc_id=doc_id,
                ingest_stage="graph_failed",
                extra_metadata={
                    "graph_error": f"{type(e).__name__}: {e}",
                    "graph_failed_stage": progress.get("latest_stage") or "unknown",
                },
            )
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status="failed",
                stage=str(progress.get("latest_stage") or "graph_construction"),
                message=f"{type(e).__name__}: {e}",
                created_at=created_at,
            )
