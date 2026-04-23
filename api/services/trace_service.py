from __future__ import annotations

from typing import Any

from api.presentation.trace_dto import (
    build_error,
    build_graph_trace_timeline,
    map_chunk_checkpoint_to_step,
    normalize_status,
)
from api.schemas.trace import TraceStepOut, TraceSummaryOut, TraceTimelineOut
from api.services.documents_service import DocumentsService
from api.services.ingest_tasks_service import IngestTasksService


class TraceService:
    """统一输出前端可消费的 trace timeline DTO。"""

    def __init__(self) -> None:
        self._documents = DocumentsService()
        self._tasks = IngestTasksService()

    def get_ingest_task_trace(self, *, task_id: str) -> TraceTimelineOut:
        task = self._tasks.get_task(task_id=task_id)
        if task is None:
            raise ValueError(f"ingest task not found: {task_id}")

        metadata = dict(task.metadata or {})
        task_kind = str(metadata.get("task_kind") or "graph_build")
        graph_progress = self._documents.get_document_graph_progress(group_id=task.group_id, doc_id=task.doc_id)
        task_step = self._build_ingest_task_step(task=task, graph_progress=graph_progress)
        graph_timeline = build_graph_trace_timeline(graph_progress, trace_id=str(task.trace_id or task.task_id))

        if task_kind == "chunk_retry":
            steps = [task_step, *self._build_chunk_retry_steps(task=task)]
        else:
            steps = [task_step, *graph_timeline.steps]
        steps.sort(key=self._step_sort_key)

        summary = TraceSummaryOut(
            trace_id=str(task.trace_id or task.task_id),
            status=normalize_status(task.status),
            current_step_name=str(task.stage or graph_timeline.summary.current_step_name or ""),
            total_steps=len(steps),
            completed_steps=sum(1 for step in steps if step.status == "completed"),
            running_steps=sum(1 for step in steps if step.status == "running"),
            failed_steps=sum(1 for step in steps if step.status == "failed"),
            pending_steps=sum(1 for step in steps if step.status == "pending"),
            total_chunks=int(graph_progress.get("total_chunks") or 0),
            completed_chunks=int(graph_progress.get("completed_chunks") or 0),
            failed_chunks=int(graph_progress.get("failed_chunks") or 0),
            processing_chunks=int(graph_progress.get("processing_chunks") or 0),
            pending_chunks=int(graph_progress.get("pending_chunks") or 0),
        )
        return TraceTimelineOut(summary=summary, steps=steps)

    def _build_chunk_retry_steps(self, *, task) -> list[TraceStepOut]:
        metadata = dict(task.metadata or {})
        chunk_id = str(metadata.get("target_chunk_id") or "").strip()
        if not chunk_id:
            return []
        chunk = self._documents.get_doc_chunk_detail(group_id=task.group_id, doc_id=task.doc_id, chunk_id=chunk_id)
        if chunk is None:
            return []
        step = map_chunk_checkpoint_to_step(chunk, trace_id=str(task.trace_id or task.task_id))
        payload = dict(step.payload or {})
        payload.update(
            {
                "task_id": task.task_id,
                "task_kind": "chunk_retry",
                "target_chunk_id": chunk_id,
                "target_chunk_index": metadata.get("target_chunk_index"),
                "follow_up_task_id": metadata.get("follow_up_task_id") or "",
                "follow_up_task_status": metadata.get("follow_up_task_status") or "",
            }
        )
        step.title = f"Chunk Retry {int(getattr(chunk.chunk, 'index', 0)) + 1}"
        step.kind = "chunk_retry"
        step.payload = payload
        return [step]

    def _build_ingest_task_step(self, *, task, graph_progress: dict[str, Any]) -> TraceStepOut:
        metadata = dict(task.metadata or {})
        payload = {
            "task_id": task.task_id,
            "group_id": task.group_id,
            "doc_id": task.doc_id,
            "doc_name": task.doc_name,
            "doc_time": task.doc_time,
            "message": task.message,
            "retry_count": int(task.retry_count or 0),
            "cancel_requested": bool(task.cancel_requested),
            "graph_progress": {
                "total_chunks": int(graph_progress.get("total_chunks") or 0),
                "completed_chunks": int(graph_progress.get("completed_chunks") or 0),
                "failed_chunks": int(graph_progress.get("failed_chunks") or 0),
                "processing_chunks": int(graph_progress.get("processing_chunks") or 0),
                "pending_chunks": int(graph_progress.get("pending_chunks") or 0),
            },
            **metadata,
        }
        task_kind = str(metadata.get("task_kind") or "graph_build")
        return TraceStepOut(
            step_id=f"ingest-task:{task.task_id}",
            trace_id=str(task.trace_id or task.task_id),
            source="ingest",
            kind="ingest_task",
            event="ingest.task",
            step_name=str(task.stage or "queued"),
            title="Chunk Retry Task" if task_kind == "chunk_retry" else "Ingest Task",
            status=normalize_status(task.status),
            started_at=str(task.created_at or ""),
            ended_at=str(task.updated_at or "") if normalize_status(task.status) in {"completed", "failed"} else "",
            updated_at=str(task.updated_at or ""),
            error=build_error(
                error_type="IngestTaskError" if normalize_status(task.status) == "failed" else "",
                message=str(task.message or "") if normalize_status(task.status) == "failed" else "",
                detail=payload if normalize_status(task.status) == "failed" else {},
            ),
            payload=payload,
        )

    @staticmethod
    def _step_sort_key(step: TraceStepOut) -> tuple[str, str]:
        return (
            str(step.updated_at or step.started_at or ""),
            str(step.step_id or ""),
        )
