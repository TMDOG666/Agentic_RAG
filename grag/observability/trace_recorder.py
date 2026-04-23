from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from grag.config import get_config_manager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(slots=True)
class TraceContext:
    trace_id: str
    trace_type: str
    name: str
    started_at: str
    group_id: str = ""
    doc_id: str = ""
    doc_name: str = ""
    task_id: str = ""
    request_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InvocationRecord:
    trace_id: str
    invocation_id: str
    kind: str
    name: str
    status: str
    started_at: str
    ended_at: str
    latency_ms: float
    input: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    usage: Dict[str, Any] = field(default_factory=dict)
    error: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceEventRecord:
    trace_id: str
    event_id: str
    source: str
    event_type: str
    timestamp: str
    payload: Dict[str, Any] = field(default_factory=dict)


_TRACE_RECORDER_VAR: contextvars.ContextVar["TraceRecorder | None"] = contextvars.ContextVar(
    "grag_trace_recorder",
    default=None,
)


def get_current_trace_recorder() -> "TraceRecorder | None":
    return _TRACE_RECORDER_VAR.get()


@contextlib.contextmanager
def bind_trace_recorder(recorder: "TraceRecorder | None") -> Iterator[None]:
    token = _TRACE_RECORDER_VAR.set(recorder)
    try:
        yield
    finally:
        _TRACE_RECORDER_VAR.reset(token)


class TraceRecorder:
    """统一 trace 记录器。

    第一阶段先落地为 JSONL 文件，便于后续 replay / 检索 / UI 接入。
    """

    def __init__(self, *, context: TraceContext, output_dir: str) -> None:
        self.context = context
        self.trace_id = context.trace_id
        self._output_dir = output_dir
        self._output_path = os.path.join(output_dir, f"{self.trace_id}.jsonl")
        self._lock = threading.Lock()
        self._open_invocations: dict[str, dict[str, Any]] = {}
        self._closed = False

        os.makedirs(self._output_dir, exist_ok=True)
        self._write_record(
            {
                "record_type": "trace_start",
                "trace": asdict(self.context),
            }
        )

    @classmethod
    def create(
        cls,
        *,
        trace_type: str,
        name: str,
        group_id: str = "",
        doc_id: str = "",
        doc_name: str = "",
        task_id: str = "",
        request_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "TraceRecorder":
        settings = get_config_manager().get_settings()
        workspace_dir = str(getattr(settings.system, "workspace_dir", "./data"))
        output_dir = os.path.join(workspace_dir, "traces", datetime.now().strftime("%Y%m%d"))
        context = TraceContext(
            trace_id=uuid.uuid4().hex,
            trace_type=str(trace_type or "generic"),
            name=str(name or trace_type or "trace"),
            started_at=_utc_now(),
            group_id=str(group_id or ""),
            doc_id=str(doc_id or ""),
            doc_name=str(doc_name or ""),
            task_id=str(task_id or ""),
            request_id=str(request_id or ""),
            metadata=_json_safe(metadata or {}),
        )
        return cls(context=context, output_dir=output_dir)

    @property
    def output_path(self) -> str:
        return self._output_path

    def _write_record(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(_json_safe(payload), ensure_ascii=False, default=str)
        with self._lock:
            with open(self._output_path, "a", encoding="utf-8") as file:
                file.write(line + "\n")

    def record_event(self, *, source: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> str:
        event = TraceEventRecord(
            trace_id=self.trace_id,
            event_id=uuid.uuid4().hex,
            source=str(source or "runtime"),
            event_type=str(event_type or "event"),
            timestamp=_utc_now(),
            payload=_json_safe(payload or {}),
        )
        self._write_record({"record_type": "event", "event": asdict(event)})
        return event.event_id

    def start_invocation(
        self,
        *,
        kind: str,
        name: str,
        input_payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        invocation_id: Optional[str] = None,
    ) -> str:
        current_id = str(invocation_id or uuid.uuid4().hex)
        start_perf = time.perf_counter()
        started_at = _utc_now()
        self._open_invocations[current_id] = {
            "kind": str(kind or "generic"),
            "name": str(name or kind or "invocation"),
            "input": _json_safe(input_payload or {}),
            "metadata": _json_safe(metadata or {}),
            "started_at": started_at,
            "start_perf": start_perf,
        }
        self._write_record(
            {
                "record_type": "invocation_start",
                "trace_id": self.trace_id,
                "invocation_id": current_id,
                "kind": str(kind or "generic"),
                "name": str(name or kind or "invocation"),
                "timestamp": started_at,
                "input": _json_safe(input_payload or {}),
                "metadata": _json_safe(metadata or {}),
            }
        )
        return current_id

    def finish_invocation(
        self,
        invocation_id: str,
        *,
        status: str = "completed",
        output_payload: Optional[Dict[str, Any]] = None,
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> InvocationRecord:
        state = self._open_invocations.pop(str(invocation_id), None)
        ended_at = _utc_now()
        if state is None:
            state = {
                "kind": "generic",
                "name": "unknown",
                "input": {},
                "metadata": {},
                "started_at": ended_at,
                "start_perf": time.perf_counter(),
            }

        latency_ms = round((time.perf_counter() - float(state["start_perf"])) * 1000, 2)
        merged_metadata = dict(state.get("metadata") or {})
        merged_metadata.update(_json_safe(metadata or {}))
        record = InvocationRecord(
            trace_id=self.trace_id,
            invocation_id=str(invocation_id),
            kind=str(state.get("kind") or "generic"),
            name=str(state.get("name") or "unknown"),
            status=str(status or "completed"),
            started_at=str(state.get("started_at") or ended_at),
            ended_at=ended_at,
            latency_ms=latency_ms,
            input=_json_safe(state.get("input") or {}),
            output=_json_safe(output_payload or {}),
            usage=_json_safe(usage or {}),
            error=_json_safe(error or {}),
            metadata=merged_metadata,
        )
        self._write_record({"record_type": "invocation_end", "invocation": asdict(record)})
        return record

    def record_span(
        self,
        *,
        name: str,
        duration_ms: float,
        attrs: Optional[Dict[str, Any]] = None,
        status: str = "completed",
    ) -> None:
        self._write_record(
            {
                "record_type": "span",
                "trace_id": self.trace_id,
                "name": str(name or "span"),
                "timestamp": _utc_now(),
                "duration_ms": float(duration_ms),
                "status": str(status or "completed"),
                "attrs": _json_safe(attrs or {}),
            }
        )

    def record_result(self, *, step: str, payload: Any) -> None:
        self._write_record(
            {
                "record_type": "result",
                "trace_id": self.trace_id,
                "step": str(step or "unknown"),
                "timestamp": _utc_now(),
                "payload": _json_safe(payload),
            }
        )

    def close(self, *, status: str = "completed", metadata: Optional[Dict[str, Any]] = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._write_record(
            {
                "record_type": "trace_end",
                "trace_id": self.trace_id,
                "status": str(status or "completed"),
                "timestamp": _utc_now(),
                "metadata": _json_safe(metadata or {}),
            }
        )
