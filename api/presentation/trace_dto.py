from __future__ import annotations

import uuid
from typing import Any

from api.schemas.trace import (
    TraceErrorOut,
    TraceStepOut,
    TraceStreamEventOut,
    TraceSummaryOut,
    TraceTimelineOut,
    TraceTokenUsageOut,
)


def normalize_status(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"completed", "done", "success", "succeeded"}:
        return "completed"
    if raw in {"failed", "error"}:
        return "failed"
    if raw in {"running", "processing", "in_progress", "active"}:
        return "running"
    if raw in {"pending", "queued", "waiting"}:
        return "pending"
    return raw or "pending"


def build_token_usage(payload: dict[str, Any] | None) -> TraceTokenUsageOut | None:
    data = dict(payload or {})
    input_tokens = int(data.get("input_tokens") or 0)
    output_tokens = int(data.get("output_tokens") or 0)
    total_tokens = int(data.get("total_tokens") or 0)
    if input_tokens <= 0 and output_tokens <= 0 and total_tokens <= 0:
        return None
    return TraceTokenUsageOut(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        is_estimated=bool(data.get("is_estimated") or False),
    )


def build_error(error_type: str = "", message: str = "", detail: dict[str, Any] | None = None) -> TraceErrorOut | None:
    if not str(error_type or "").strip() and not str(message or "").strip() and not (detail or {}):
        return None
    return TraceErrorOut(
        error_type=str(error_type or ""),
        message=str(message or ""),
        detail=dict(detail or {}),
    )


def _infer_kind(event: str, payload: dict[str, Any]) -> str:
    if event.startswith("assistant."):
        return "assistant"
    if event.startswith("agent.think") or event == "usage.llm":
        return "llm"
    if event.startswith("skill."):
        return "skill"
    if event.startswith("tool."):
        return "tool"
    if event.startswith("retrieval."):
        return "retrieval"
    if event.startswith("run."):
        return "run"
    if event == "trace.ready":
        return "trace"
    if event == "meta":
        return "meta"
    if event == "done":
        return "assistant"
    if "tool_name" in payload:
        return "tool"
    return "system"


def _infer_title(event: str, payload: dict[str, Any]) -> str:
    if event == "meta":
        return "会话开始"
    if event == "done":
        return "回答完成"
    if event == "trace.ready":
        return "Trace 已就绪"
    if event == "usage.llm":
        return "LLM Token 使用"
    if event == "agent.tool_calls":
        return "模型选择工具"
    if event.startswith("assistant."):
        return "助手输出"
    if event.startswith("agent.think"):
        return "模型思考"
    if event.startswith("skill.load"):
        return "加载技能"
    if event.startswith("skill.file"):
        return "读取技能文件"
    if event.startswith("skill.script"):
        return "执行技能脚本"
    if event.startswith("tool."):
        return str(payload.get("tool_name") or "工具调用")
    if event.startswith("retrieval.plan"):
        return "检索计划"
    if event.startswith("retrieval.step"):
        return f"检索步骤 {payload.get('step') or ''}".strip()
    return event


def _infer_status(event: str, payload: dict[str, Any]) -> str:
    explicit = normalize_status(payload.get("status"))
    if explicit != "pending" or str(payload.get("status") or "").strip():
        return explicit
    if event.endswith(".error") or event in {"agent.error", "run.failed"}:
        return "failed"
    if event.endswith(".start") or event in {"assistant.start", "run.start"}:
        return "running"
    if event.endswith(".end") or event.endswith(".done") or event in {"done", "trace.ready", "run.complete"}:
        return "completed"
    if event == "assistant.chunk":
        return "running"
    return "running"


def map_agent_event_to_dto(event: dict[str, Any], *, trace_id: str = "") -> TraceStreamEventOut:
    raw_event = str(event.get("type") or "message")
    payload = dict(event or {})
    payload.pop("type", None)
    status = _infer_status(raw_event, payload)
    timestamp = str(payload.get("timestamp") or payload.get("updated_at") or "")
    started_at = str(payload.get("started_at") or timestamp)
    updated_at = str(payload.get("updated_at") or timestamp or started_at)
    ended_at = str(payload.get("ended_at") or (updated_at if status in {"completed", "failed"} else ""))
    error = build_error(
        error_type=str(payload.get("error_type") or ""),
        message=str(payload.get("error") or ""),
        detail=payload if raw_event.endswith(".error") or raw_event in {"agent.error", "run.failed"} else {},
    )
    tokens = build_token_usage(payload)
    step = TraceStepOut(
        step_id=str(payload.get("task_id") or payload.get("invocation_id") or uuid.uuid4().hex),
        trace_id=str(trace_id or payload.get("trace_id") or ""),
        source="agent",
        kind=_infer_kind(raw_event, payload),
        event=raw_event,
        step_name=str(
            payload.get("step_name")
            or payload.get("tool_name")
            or payload.get("skill_name")
            or payload.get("label")
            or raw_event
        ),
        title=_infer_title(raw_event, payload),
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        updated_at=updated_at,
        latency_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
        tokens=tokens,
        error=error,
        payload=payload,
    )
    return TraceStreamEventOut(
        trace_id=str(trace_id or payload.get("trace_id") or ""),
        event=raw_event,
        step=step,
        payload=payload,
    )


def map_pipeline_checkpoint_to_step(stage: str, checkpoint: dict[str, Any], *, trace_id: str = "") -> TraceStepOut:
    payload = dict((checkpoint or {}).get("payload") or {})
    status = normalize_status(checkpoint.get("status"))
    updated_at = str(checkpoint.get("updated_at") or payload.get("updated_at") or "")
    started_at = str(payload.get("started_at") or updated_at)
    ended_at = updated_at if status in {"completed", "failed"} else ""
    error = build_error(
        message=str(checkpoint.get("error") or ""),
        detail=payload if str(checkpoint.get("error") or "").strip() else {},
    )
    return TraceStepOut(
        step_id=f"pipeline:{stage}",
        trace_id=trace_id,
        source="ingest",
        kind="pipeline_checkpoint",
        event="ingest.checkpoint",
        step_name=str(stage),
        title=str(stage),
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        updated_at=updated_at,
        latency_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
        tokens=build_token_usage(payload),
        error=error,
        payload=payload,
    )


def map_chunk_checkpoint_to_step(chunk: Any, *, trace_id: str = "") -> TraceStepOut:
    status = normalize_status(getattr(chunk, "status", ""))
    updated_at = str(getattr(chunk, "updated_at", "") or "")
    payload = {
        "chunk_id": str(chunk.chunk_id),
        "chunk_index": int(chunk.index),
        "resolved_text": str(getattr(chunk, "resolved_text", "") or ""),
        "entity_relation_raw": str(getattr(chunk, "entity_relation_raw", "") or ""),
        "parsed_entities": list(getattr(chunk, "parsed_entities", []) or []),
        "parsed_relations": list(getattr(chunk, "parsed_relations", []) or []),
        "parse_errors": list(getattr(chunk, "parse_errors", []) or []),
    }
    return TraceStepOut(
        step_id=f"chunk:{chunk.chunk_id}",
        trace_id=trace_id,
        source="ingest",
        kind="chunk_checkpoint",
        event="ingest.chunk",
        step_name=f"chunk_{int(chunk.index)}",
        title=f"Chunk {int(chunk.index)}",
        status=status,
        started_at=updated_at,
        ended_at=updated_at if status in {"completed", "failed"} else "",
        updated_at=updated_at,
        error=build_error(message=str(getattr(chunk, "error", "") or ""), detail=payload),
        payload=payload,
    )


def build_graph_trace_timeline(
    graph_progress: dict[str, Any],
    *,
    trace_id: str = "",
    chunks: list[Any] | None = None,
) -> TraceTimelineOut:
    pipeline = dict(graph_progress.get("pipeline") or {})
    steps = [map_pipeline_checkpoint_to_step(stage, checkpoint, trace_id=trace_id) for stage, checkpoint in pipeline.items()]
    if chunks:
        steps.extend(map_chunk_checkpoint_to_step(chunk, trace_id=trace_id) for chunk in chunks)

    summary = TraceSummaryOut(
        trace_id=trace_id,
        status=normalize_status(graph_progress.get("latest_status")),
        current_step_name=str(graph_progress.get("latest_stage") or ""),
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
