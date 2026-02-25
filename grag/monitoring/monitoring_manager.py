# Monitoring Manager Module
 
from __future__ import annotations
 
import json
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional
 
from ..config import get_config_manager
from grag.monitoring.logger import get_logger
 
 
logger = get_logger(__name__)
 
 
@dataclass
class SpanRecord:
    name: str
    start_ts: float
    end_ts: float
    duration_ms: float
    attrs: Dict[str, Any] = field(default_factory=dict)
 
 
_CURRENT_MONITOR: ContextVar[Optional["MonitoringManager"]] = ContextVar("grag_current_monitor", default=None)
 
 
def get_current_monitor() -> Optional["MonitoringManager"]:
    return _CURRENT_MONITOR.get()
 
 
@contextmanager
def use_monitor(monitor: Optional["MonitoringManager"]) -> Iterator[None]:
    token = _CURRENT_MONITOR.set(monitor)
    try:
        yield
    finally:
        _CURRENT_MONITOR.reset(token)
 
 
class MonitoringManager:
    def __init__(
        self,
        *,
        run_id: Optional[str] = None,
        doc_name: Optional[str] = None,
        enabled: Optional[bool] = None,
        base_attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        settings = get_config_manager().get_settings()
        monitoring_cfg = getattr(settings.system, "monitoring", {}) or {}
 
        resolved_enabled = bool(monitoring_cfg.get("enabled", True))
        if enabled is not None:
            resolved_enabled = bool(enabled)
 
        self.enabled: bool = resolved_enabled
        self.run_id: str = run_id or uuid.uuid4().hex
        self.doc_name: Optional[str] = doc_name
        self.base_attrs: Dict[str, Any] = dict(base_attrs or {})
        if self.doc_name:
            self.base_attrs.setdefault("doc_name", self.doc_name)
 
        self.counters: Dict[str, int] = {}
        self.observations: Dict[str, List[float]] = {}
        self.spans: List[SpanRecord] = []
        self.errors: List[str] = []
        self.results: Dict[str, Any] = {}
 
        self._export_json: bool = bool(monitoring_cfg.get("export_json", False))
        self._export_dir: str = str(
            monitoring_cfg.get("export_dir")
            or os.path.join(str(getattr(settings.system, "workspace_dir", "./data")), "monitoring")
        )
        self._record_results: bool = bool(monitoring_cfg.get("record_results", True))
        self._max_result_chars: int = int(monitoring_cfg.get("max_result_chars", 2000))
        self._max_result_items: int = int(monitoring_cfg.get("max_result_items", 200))
 
    def inc(self, name: str, value: int = 1) -> None:
        if not self.enabled:
            return
        self.counters[name] = int(self.counters.get(name, 0)) + int(value)
 
    def observe(self, name: str, value: float) -> None:
        if not self.enabled:
            return
        self.observations.setdefault(name, []).append(float(value))
 
    def add_error(self, msg: str) -> None:
        if not self.enabled:
            return
        self.errors.append(str(msg))
 
    def record_result(self, step: str, payload: Any) -> None:
        if not self.enabled:
            return
        if not self._record_results:
            return
        step = str(step or "").strip() or "unknown"
        if len(self.results) >= self._max_result_items and step not in self.results:
            return
        self.results[step] = self._sanitize_result(payload)
 
    def _sanitize_result(self, payload: Any) -> Any:
        try:
            if payload is None:
                return None
            if isinstance(payload, (int, float, bool)):
                return payload
            if isinstance(payload, str):
                return self._truncate(payload)
            if isinstance(payload, dict):
                out: Dict[str, Any] = {}
                for k, v in payload.items():
                    if len(out) >= self._max_result_items:
                        break
                    out[str(k)] = self._sanitize_result(v)
                return out
            if isinstance(payload, (list, tuple)):
                out_list: List[Any] = []
                for i, it in enumerate(payload):
                    if i >= self._max_result_items:
                        break
                    out_list.append(self._sanitize_result(it))
                return out_list
 
            # 最后一层兜底：转成字符串（并截断）
            return self._truncate(str(payload))
        except Exception as e:
            self.add_error(f"record_result sanitize failed: {type(e).__name__}: {e}")
            return None
 
    def _truncate(self, s: str) -> str:
        s = s or ""
        if self._max_result_chars <= 0:
            return ""
        if len(s) <= self._max_result_chars:
            return s
        return s[: self._max_result_chars] + "...<TRUNCATED>"
 
    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            yield attrs
            return
 
        merged_attrs = {**self.base_attrs, **attrs}
        start = time.perf_counter()
        start_ts = time.time()
        try:
            yield merged_attrs
        except Exception as e:
            self.inc(f"{name}.exceptions", 1)
            self.add_error(f"{name}: {type(e).__name__}: {e}")
            raise
        finally:
            end = time.perf_counter()
            end_ts = time.time()
            dur_ms = (end - start) * 1000.0
            self.observe(f"{name}.duration_ms", dur_ms)
            self.spans.append(
                SpanRecord(
                    name=name,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    duration_ms=dur_ms,
                    attrs=merged_attrs,
                )
            )
            logger.info(
                "span=%s duration_ms=%.2f attrs=%s",
                name,
                dur_ms,
                json.dumps(merged_attrs, ensure_ascii=False, default=str),
            )
 
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "doc_name": self.doc_name,
            "counters": dict(self.counters),
            "observations": {k: list(v) for k, v in self.observations.items()},
            "spans": [asdict(s) for s in self.spans],
            "errors": list(self.errors),
            "results": dict(self.results),
        }
 
    def export_json(self, path: Optional[str] = None) -> Optional[str]:
        if not self.enabled:
            return None
        if not (self._export_json or path):
            return None
 
        out_path = path
        if not out_path:
            os.makedirs(self._export_dir, exist_ok=True)
            out_path = os.path.join(self._export_dir, f"{self.run_id}.json")
 
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return out_path