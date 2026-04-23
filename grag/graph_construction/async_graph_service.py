from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from api.services.documents_service import DocumentsService
from api.services.ingest_tasks_service import IngestTasksService
from grag.config import ProviderType, get_config_manager
from grag.observability import TraceRecorder, bind_trace_recorder, get_current_trace_recorder
from grag.storage import IngestTaskRecord
from grag.storage.storage_impl import DataClientGraphStorage

from .graph_builder import GraphBuilder
from .graph_construction_manager import GraphConstructionStreamEvent


logger = logging.getLogger(__name__)


class AsyncGraphBuildService:
    """图谱异步构建任务调度器。

    这个类只负责三件事：
    1. 生成并维护 ingest task；
    2. 把图谱构建提交到线程池执行；
    3. 在任务运行过程中同步文档状态与失败信息。
    """

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

    @staticmethod
    def _build_task_record(
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
        updated_at: str,
    ) -> IngestTaskRecord:
        return IngestTaskRecord(
            task_id=task_id,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status=status,
            stage=stage,
            message=message,
            created_at=created_at,
            updated_at=updated_at,
        )

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
        task = self._build_task_record(
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
        task = self._build_task_record(
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
        normalized_statuses = [str(status).strip() for status in (statuses or []) if str(status).strip()]
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

        for task in self._tasks_service.list_recoverable_tasks(limit=1000):
            try:
                if self.is_task_active(task_id=task.task_id):
                    continue
                if not self._resume_task(task):
                    continue
                recovered += 1
            except Exception as exc:
                logger.warning("Failed to resume ingest task %s: %s: %s", task.task_id, type(exc).__name__, exc)
        return recovered

    def _resume_task(self, task: IngestTaskRecord) -> bool:
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
            return False

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
        return True

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
            task=self._build_task_record(
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

    def _log_runtime_config(self, *, task_id: str) -> None:
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

    def _mark_task_running(
        self,
        *,
        task_id: str,
        created_at: str,
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
        self._documents.update_document_stage(
            group_id=group_id,
            doc_id=doc_id,
            ingest_stage="graph_processing",
        )

    def _mark_task_completed(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ) -> None:
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

    def _mark_task_failed(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        error: Exception,
    ) -> None:
        progress = self._documents.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
        self._documents.update_document_stage(
            group_id=group_id,
            doc_id=doc_id,
            ingest_stage="graph_failed",
            extra_metadata={
                "graph_error": f"{type(error).__name__}: {error}",
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
            message=f"{type(error).__name__}: {error}",
            created_at=created_at,
        )

    def _create_progress_handler(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ):
        def _handle_progress(event: GraphConstructionStreamEvent) -> None:
            recorder = get_current_trace_recorder()
            if recorder is not None:
                recorder.record_event(
                    source="ingest",
                    event_type=event.event_type,
                    payload={
                        "stage": event.stage,
                        "message": event.message,
                        "group_id": event.group_id,
                        "doc_id": event.doc_id,
                        "doc_name": event.doc_name,
                        "chunk_id": event.chunk_id,
                        "chunk_index": event.chunk_index,
                        "total_chunks": event.total_chunks,
                        "payload": event.payload or {},
                    },
                )
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
                stage=event.stage,
                message=message,
                created_at=created_at,
            )

        return _handle_progress

    @staticmethod
    def _create_builder() -> GraphBuilder:
        return GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))

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
        recorder = TraceRecorder.create(
            trace_type="ingest_task",
            name="ingest.graph_build",
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            task_id=task_id,
            metadata={"doc_time": doc_time},
        )
        run_invocation_id = recorder.start_invocation(
            kind="ingest_task",
            name="ingest.graph_build",
            input_payload={
                "task_id": task_id,
                "group_id": group_id,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "doc_time": doc_time,
                "text_chars": len(text or ""),
            },
        )
        with bind_trace_recorder(recorder):
            self._log_runtime_config(task_id=task_id)
            recorder.record_event(
                source="ingest",
                event_type="ingest.task.running",
                payload={"task_id": task_id, "group_id": group_id, "doc_id": doc_id},
            )
            self._mark_task_running(
                task_id=task_id,
                created_at=created_at,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
            )
            try:
                builder = self._create_builder()
                builder.build_graph_and_save(
                    text=text,
                    doc_time=doc_time,
                    doc_name=doc_name,
                    group_id=group_id,
                    doc_id=doc_id,
                    progress_callback=self._create_progress_handler(
                        task_id=task_id,
                        created_at=created_at,
                        group_id=group_id,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        doc_time=doc_time,
                    ),
                    stream_base=False,
                )
                self._mark_task_completed(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.task.completed",
                    payload={"task_id": task_id, "group_id": group_id, "doc_id": doc_id},
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="completed",
                    output_payload={"task_id": task_id, "status": "completed"},
                )
                recorder.close(status="completed")
            except Exception as exc:
                self._mark_task_failed(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    error=exc,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.task.failed",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="failed",
                    error={"error_type": type(exc).__name__, "message": str(exc)},
                )
                recorder.close(status="failed")
