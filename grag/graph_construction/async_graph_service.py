from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from api.services.documents_service import DocumentsService
from api.services.ingest_tasks_service import IngestTasksService
from grag.config import get_config_manager
from grag.observability import TraceRecorder, bind_trace_recorder, get_current_trace_recorder
from grag.storage import IngestTaskRecord
from grag.storage.storage_impl import DataClientGraphStorage

from .graph_builder import GraphBuilder
from .graph_construction_manager import GraphConstructionStreamEvent


logger = logging.getLogger(__name__)


class IngestTaskCancelledError(RuntimeError):
    """内部取消异常。"""


class AsyncGraphBuildService:
    """图谱异步构建任务调度器。"""

    _instance: "AsyncGraphBuildService | None" = None
    _lock = Lock()
    ACTIVE_STATUSES = {"pending", "running", "recovering", "cancel_requested"}
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

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
    def _task_kind(task: IngestTaskRecord | None, default: str = "graph_build") -> str:
        metadata = dict(task.metadata or {}) if task is not None else {}
        return str(metadata.get("task_kind") or default)

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
        trace_id: str = "",
        retry_count: int = 0,
        cancel_requested: bool = False,
        metadata: dict | None = None,
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
            trace_id=trace_id,
            retry_count=retry_count,
            cancel_requested=cancel_requested,
            metadata=dict(metadata or {}),
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
            metadata={"task_kind": "graph_build"},
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

    def submit_chunk_retry(
        self,
        *,
        group_id: str,
        doc_id: str,
        chunk_id: str,
        doc_name: str,
        doc_time: str,
    ) -> IngestTaskRecord:
        now = self._now()
        chunk_index = self._resolve_chunk_index(group_id=group_id, doc_id=doc_id, chunk_id=chunk_id)
        task = self._build_task_record(
            task_id=uuid4().hex,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status="pending",
            stage="chunk_retry_queued",
            message="chunk retry queued",
            created_at=now,
            updated_at=now,
            metadata={
                "task_kind": "chunk_retry",
                "target_chunk_id": chunk_id,
                "target_chunk_index": chunk_index,
            },
        )
        self._storage.upsert_ingest_task(task=task)
        self._submit_future(
            self._run_task,
            task_id=task.task_id,
            created_at=task.created_at,
            text="",
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
        retry_count: int = 0,
        metadata: dict | None = None,
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
            retry_count=retry_count,
            metadata=metadata,
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

    def _get_task(self, *, task_id: str) -> IngestTaskRecord | None:
        return self._tasks_service.get_task(task_id=task_id)

    def _resolve_chunk_index(self, *, group_id: str, doc_id: str, chunk_id: str) -> int:
        try:
            chunks = self._documents.list_doc_chunks(group_id=group_id, doc_id=doc_id)
        except Exception:
            return -1
        for chunk in chunks:
            if str(chunk.chunk_id) == str(chunk_id):
                return int(chunk.index)
        return -1

    def get_latest_task_for_document(self, *, group_id: str, doc_id: str) -> IngestTaskRecord | None:
        if not str(group_id or "").strip() or not str(doc_id or "").strip():
            return None
        return self._tasks_service.get_latest_task(group_id=group_id, doc_id=doc_id)

    def request_cancel(self, *, task_id: str) -> IngestTaskRecord:
        task = self._get_task(task_id=task_id)
        if task is None:
            raise RuntimeError("任务不存在")
        if task.status in self.TERMINAL_STATUSES:
            return task

        next_status = "cancel_requested" if self.is_task_active(task_id=task_id) else "cancelled"
        updated = self._build_task_record(
            task_id=task.task_id,
            group_id=task.group_id,
            doc_id=task.doc_id,
            doc_name=task.doc_name,
            doc_time=task.doc_time,
            status=next_status,
            stage=task.stage or "graph_construction",
            message="task cancellation requested" if next_status == "cancel_requested" else "task cancelled",
            created_at=task.created_at,
            updated_at=self._now(),
            trace_id=task.trace_id,
            retry_count=int(task.retry_count or 0),
            cancel_requested=True,
            metadata=dict(task.metadata or {}),
        )
        self._tasks_service.upsert_task(task=updated)
        if next_status == "cancelled":
            self._documents.update_document_stage(
                group_id=task.group_id,
                doc_id=task.doc_id,
                ingest_stage="graph_cancelled",
                extra_metadata={"graph_cancel_task_id": task.task_id},
            )
        return updated

    def resume_task(self, *, task_id: str, reason: str = "manual_resume") -> IngestTaskRecord:
        task = self._get_task(task_id=task_id)
        if task is None:
            raise RuntimeError("任务不存在")
        if self.is_task_active(task_id=task.task_id):
            return task
        return self._resume_task_record(task=task, reason=reason, metadata_patch={"resume_requested_by": reason})

    def resume_document_task(
        self,
        *,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        text: str,
        reason: str = "document_retry",
        metadata_patch: dict | None = None,
    ) -> IngestTaskRecord:
        latest = self.get_latest_task_for_document(group_id=group_id, doc_id=doc_id)
        if latest is None:
            return self.submit(
                text=text,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
            )
        if self.is_task_active(task_id=latest.task_id):
            return latest
        return self._resume_task_record(
            task=latest,
            reason=reason,
            metadata_patch={"document_text_chars": len(text or ""), **dict(metadata_patch or {})},
        )

    def _ensure_not_cancel_requested(self, *, task_id: str) -> None:
        task = self._get_task(task_id=task_id)
        if task is not None and bool(task.cancel_requested):
            raise IngestTaskCancelledError("task cancellation requested")

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
        self._resume_task_record(
            task=task,
            reason="startup_recovery",
            metadata_patch={"recovered": True},
        )
        return True

    def _resume_task_record(
        self,
        *,
        task: IngestTaskRecord,
        reason: str,
        metadata_patch: dict | None = None,
    ) -> IngestTaskRecord:
        resume_metadata = {
            **dict(task.metadata or {}),
            **dict(metadata_patch or {}),
            "last_resume_reason": reason,
            "last_resume_at": self._now(),
        }
        task_kind = self._task_kind(task)
        text = ""
        if task_kind == "graph_build":
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
                    trace_id=task.trace_id,
                    retry_count=int(task.retry_count or 0),
                    cancel_requested=False,
                    metadata=dict(task.metadata or {}),
                )
                raise RuntimeError("document text missing for resume")
        self._documents.update_document_stage(
            group_id=task.group_id,
            doc_id=task.doc_id,
            ingest_stage="graph_retrying",
            extra_metadata={
                "graph_resume_task_id": task.task_id,
                "graph_resume_reason": reason,
            },
        )
        return self.submit_existing(
            task_id=task.task_id,
            created_at=task.created_at,
            text=text,
            group_id=task.group_id,
            doc_id=task.doc_id,
            doc_name=task.doc_name,
            doc_time=task.doc_time,
            initial_status="recovering",
            initial_stage=task.stage or "queued",
            initial_message=f"{reason}: {task.message}",
            retry_count=int(task.retry_count or 0) + 1,
            metadata=resume_metadata,
        )

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
        trace_id: str = "",
        retry_count: int = 0,
        cancel_requested: bool = False,
        metadata: dict | None = None,
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
                trace_id=trace_id,
                retry_count=retry_count,
                cancel_requested=cancel_requested,
                metadata=metadata,
            )
        )

    def _log_runtime_config(self, *, task_id: str) -> None:
        try:
            manager = get_config_manager()
            if not manager.reload_config():
                raise RuntimeError("reload grag_config.yaml failed")
            for line in manager.format_runtime_snapshot_lines():
                logger.info("Ingest task %s runtime config: %s", task_id, line)
        except Exception as exc:
            logger.warning("Failed to reload config for ingest task %s: %s: %s", task_id, type(exc).__name__, exc)

    def _transition_task(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        status: str,
        stage: str,
        message: str,
        trace_id: str = "",
        metadata_patch: dict | None = None,
        document_stage: str | None = None,
        document_metadata: dict | None = None,
    ) -> None:
        current = self._get_task(task_id=task_id)
        metadata = dict(current.metadata or {}) if current is not None else {}
        metadata.update(dict(metadata_patch or {}))
        self._update_task(
            task_id=task_id,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status=status,
            stage=stage,
            message=message,
            created_at=created_at,
            trace_id=trace_id or str(current.trace_id or "") if current is not None else trace_id,
            retry_count=int(current.retry_count or 0) if current is not None else 0,
            cancel_requested=bool(current.cancel_requested) if current is not None else False,
            metadata=metadata,
        )
        if document_stage:
            self._documents.update_document_stage(
                group_id=group_id,
                doc_id=doc_id,
                ingest_stage=document_stage,
                extra_metadata=document_metadata or {},
            )

    def _mark_task_running(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            status="running",
            stage="graph_construction",
            message="graph construction in progress",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            document_stage="graph_processing",
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
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            status="completed",
            stage="done",
            message="graph construction completed",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            document_stage="graph_completed",
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
        trace_id: str = "",
    ) -> None:
        progress = self._documents.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
        self._transition_task(
            task_id=task_id,
            status="failed",
            stage=str(progress.get("latest_stage") or "graph_construction"),
            message=f"{type(error).__name__}: {error}",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            metadata_patch={
                "last_error_type": type(error).__name__,
                "last_error_message": str(error),
            },
            document_stage="graph_failed",
            document_metadata={
                "graph_error": f"{type(error).__name__}: {error}",
                "graph_failed_stage": progress.get("latest_stage") or "unknown",
            },
        )

    def _mark_task_cancelled(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status="cancelled",
            stage="cancelled",
            message="graph construction cancelled",
            trace_id=trace_id,
            metadata_patch={"cancelled_at": self._now()},
            document_stage="graph_cancelled",
            document_metadata={"graph_cancelled_task_id": task_id},
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
            self._ensure_not_cancel_requested(task_id=task_id)
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
                        "status": "running",
                        "step_name": event.stage,
                        "updated_at": self._now(),
                        "payload": event.payload or {},
                    },
                )
            message = event.message
            if event.chunk_index is not None and event.total_chunks:
                message = f"{message} ({event.chunk_index + 1}/{event.total_chunks})"
            current = self._get_task(task_id=task_id)
            current_metadata = dict(current.metadata or {}) if current is not None else {}
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
                trace_id=str(current.trace_id or "") if current is not None else "",
                retry_count=int(current.retry_count or 0) if current is not None else 0,
                cancel_requested=bool(current.cancel_requested) if current is not None else False,
                metadata={
                    **current_metadata,
                    "last_progress_stage": event.stage,
                    "last_progress_message": event.message,
                    "last_progress_at": self._now(),
                },
            )

        return _handle_progress

    @staticmethod
    def _create_builder() -> GraphBuilder:
        return GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))

    def _mark_chunk_task_running(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            status="running",
            stage="chunk_retry",
            message="chunk retry in progress",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            document_stage="graph_retrying",
        )

    def _mark_chunk_task_completed(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        trace_id: str = "",
        metadata_patch: dict | None = None,
    ) -> None:
        self._transition_task(
            task_id=task_id,
            status="completed",
            stage="done",
            message="chunk retry completed",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            metadata_patch=metadata_patch,
        )

    def _mark_chunk_task_failed(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        error: Exception,
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            status="failed",
            stage="chunk_retry",
            message=f"{type(error).__name__}: {error}",
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            trace_id=trace_id,
            metadata_patch={
                "last_error_type": type(error).__name__,
                "last_error_message": str(error),
            },
            document_stage="graph_failed",
            document_metadata={
                "graph_error": f"{type(error).__name__}: {error}",
                "graph_failed_stage": "chunk_retry",
            },
        )

    def _mark_chunk_task_cancelled(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        trace_id: str = "",
    ) -> None:
        self._transition_task(
            task_id=task_id,
            created_at=created_at,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            status="cancelled",
            stage="cancelled",
            message="chunk retry cancelled",
            trace_id=trace_id,
            metadata_patch={"cancelled_at": self._now()},
            document_stage="graph_cancelled",
            document_metadata={"graph_cancelled_task_id": task_id},
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
        task = self._get_task(task_id=task_id)
        task_kind = self._task_kind(task)
        if task_kind == "chunk_retry":
            self._run_chunk_retry_task(
                task_id=task_id,
                created_at=created_at,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
            )
            return
        self._run_graph_task(
            task_id=task_id,
            created_at=created_at,
            text=text,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
        )

    def _run_graph_task(
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
            current = self._get_task(task_id=task_id)
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status=str(current.status if current is not None else "pending"),
                stage=str(current.stage if current is not None else "queued"),
                message=str(current.message if current is not None else "graph build queued"),
                created_at=created_at,
                trace_id=recorder.trace_id,
                retry_count=int(current.retry_count or 0) if current is not None else 0,
                cancel_requested=bool(current.cancel_requested) if current is not None else False,
                metadata=dict(current.metadata or {}) if current is not None else {},
            )
            recorder.record_event(
                source="ingest",
                event_type="ingest.task.running",
                payload={
                    "task_id": task_id,
                    "group_id": group_id,
                    "doc_id": doc_id,
                    "trace_id": recorder.trace_id,
                    "status": "running",
                    "step_name": "graph_construction",
                    "updated_at": self._now(),
                },
            )
            self._mark_task_running(
                task_id=task_id,
                created_at=created_at,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                trace_id=recorder.trace_id,
            )
            try:
                self._ensure_not_cancel_requested(task_id=task_id)
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
                    trace_id=recorder.trace_id,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.task.completed",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "trace_id": recorder.trace_id,
                        "status": "completed",
                        "step_name": "graph_construction",
                        "updated_at": self._now(),
                    },
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="completed",
                    output_payload={"task_id": task_id, "status": "completed"},
                )
                recorder.close(status="completed")
            except IngestTaskCancelledError as exc:
                self._mark_task_cancelled(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    trace_id=recorder.trace_id,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.task.cancelled",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "trace_id": recorder.trace_id,
                        "status": "completed",
                        "step_name": "cancelled",
                        "updated_at": self._now(),
                        "message": str(exc),
                    },
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="cancelled",
                    output_payload={"task_id": task_id, "status": "cancelled"},
                )
                recorder.close(status="cancelled")
            except Exception as exc:
                self._mark_task_failed(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    error=exc,
                    trace_id=recorder.trace_id,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.task.failed",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "trace_id": recorder.trace_id,
                        "status": "failed",
                        "step_name": "graph_construction",
                        "updated_at": self._now(),
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

    def _run_chunk_retry_task(
        self,
        *,
        task_id: str,
        created_at: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ) -> None:
        current = self._get_task(task_id=task_id)
        metadata = dict(current.metadata or {}) if current is not None else {}
        chunk_id = str(metadata.get("target_chunk_id") or "").strip()
        chunk_index = int(metadata.get("target_chunk_index") or -1)
        if not chunk_id:
            raise RuntimeError("chunk retry target missing")

        recorder = TraceRecorder.create(
            trace_type="ingest_task",
            name="ingest.chunk_retry",
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            task_id=task_id,
            metadata={"doc_time": doc_time, "chunk_id": chunk_id, "chunk_index": chunk_index},
        )
        run_invocation_id = recorder.start_invocation(
            kind="ingest_task",
            name="ingest.chunk_retry",
            input_payload={
                "task_id": task_id,
                "group_id": group_id,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "doc_time": doc_time,
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
            },
        )
        with bind_trace_recorder(recorder):
            self._log_runtime_config(task_id=task_id)
            current = self._get_task(task_id=task_id)
            self._update_task(
                task_id=task_id,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                status=str(current.status if current is not None else "pending"),
                stage=str(current.stage if current is not None else "chunk_retry_queued"),
                message=str(current.message if current is not None else "chunk retry queued"),
                created_at=created_at,
                trace_id=recorder.trace_id,
                retry_count=int(current.retry_count or 0) if current is not None else 0,
                cancel_requested=bool(current.cancel_requested) if current is not None else False,
                metadata=dict(current.metadata or {}) if current is not None else {},
            )
            recorder.record_event(
                source="ingest",
                event_type="ingest.chunk_retry.running",
                payload={
                    "task_id": task_id,
                    "group_id": group_id,
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "trace_id": recorder.trace_id,
                    "status": "running",
                    "step_name": "chunk_retry",
                    "updated_at": self._now(),
                },
            )
            self._mark_chunk_task_running(
                task_id=task_id,
                created_at=created_at,
                group_id=group_id,
                doc_id=doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                trace_id=recorder.trace_id,
            )
            try:
                self._ensure_not_cancel_requested(task_id=task_id)
                builder = self._create_builder()
                builder.retry_single_chunk(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    event_callback=self._create_progress_handler(
                        task_id=task_id,
                        created_at=created_at,
                        group_id=group_id,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        doc_time=doc_time,
                    ),
                )
                progress = self._documents.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
                metadata_patch: dict[str, object] = {
                    "target_chunk_id": chunk_id,
                    "target_chunk_index": chunk_index,
                    "completed_chunks": int(progress.get("completed_chunks") or 0),
                    "failed_chunks": int(progress.get("failed_chunks") or 0),
                    "processing_chunks": int(progress.get("processing_chunks") or 0),
                }
                follow_up_task = None
                if self._documents._all_chunks_completed(progress):
                    follow_up_task = self.resume_document_task(
                        group_id=group_id,
                        doc_id=doc_id,
                        doc_name=doc_name,
                        doc_time=doc_time,
                        text=self._documents.get_document_text(group_id=group_id, doc_id=doc_id),
                        reason="chunk_retry_resume",
                        metadata_patch={
                            "retry_trigger": "chunk_retry_task",
                            "retry_source_task_id": task_id,
                            "retry_source_chunk_id": chunk_id,
                        },
                    )
                    metadata_patch["follow_up_task_id"] = follow_up_task.task_id
                    metadata_patch["follow_up_task_status"] = follow_up_task.status
                self._mark_chunk_task_completed(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    trace_id=recorder.trace_id,
                    metadata_patch=metadata_patch,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.chunk_retry.completed",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "trace_id": recorder.trace_id,
                        "status": "completed",
                        "step_name": "chunk_retry",
                        "updated_at": self._now(),
                        "follow_up_task_id": metadata_patch.get("follow_up_task_id") or "",
                    },
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="completed",
                    output_payload={"task_id": task_id, "status": "completed", **metadata_patch},
                )
                recorder.close(status="completed")
            except IngestTaskCancelledError as exc:
                self._mark_chunk_task_cancelled(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    trace_id=recorder.trace_id,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.chunk_retry.cancelled",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "trace_id": recorder.trace_id,
                        "status": "completed",
                        "step_name": "cancelled",
                        "updated_at": self._now(),
                        "message": str(exc),
                    },
                )
                recorder.finish_invocation(
                    run_invocation_id,
                    status="cancelled",
                    output_payload={"task_id": task_id, "status": "cancelled"},
                )
                recorder.close(status="cancelled")
            except Exception as exc:
                self._mark_chunk_task_failed(
                    task_id=task_id,
                    created_at=created_at,
                    group_id=group_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    doc_time=doc_time,
                    error=exc,
                    trace_id=recorder.trace_id,
                )
                recorder.record_event(
                    source="ingest",
                    event_type="ingest.chunk_retry.failed",
                    payload={
                        "task_id": task_id,
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "trace_id": recorder.trace_id,
                        "status": "failed",
                        "step_name": "chunk_retry",
                        "updated_at": self._now(),
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
