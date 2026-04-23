from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TraceTokenUsageOut(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    is_estimated: bool = False


class TraceErrorOut(BaseModel):
    error_type: str = ""
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class TraceStepOut(BaseModel):
    step_id: str
    parent_step_id: str | None = None
    trace_id: str = ""
    source: str
    kind: str
    event: str
    step_name: str
    title: str
    status: str
    started_at: str = ""
    ended_at: str = ""
    updated_at: str = ""
    latency_ms: float | None = None
    tokens: TraceTokenUsageOut | None = None
    error: TraceErrorOut | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceSummaryOut(BaseModel):
    trace_id: str = ""
    status: str = ""
    current_step_name: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    running_steps: int = 0
    failed_steps: int = 0
    pending_steps: int = 0
    total_chunks: int = 0
    completed_chunks: int = 0
    failed_chunks: int = 0
    processing_chunks: int = 0
    pending_chunks: int = 0


class TraceTimelineOut(BaseModel):
    summary: TraceSummaryOut
    steps: list[TraceStepOut] = Field(default_factory=list)


class TraceStreamEventOut(BaseModel):
    schema_version: str = "1.0"
    stream: str = "trace"
    trace_id: str = ""
    event: str
    step: TraceStepOut
    payload: dict[str, Any] = Field(default_factory=dict)
