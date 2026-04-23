from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.schemas.trace import TraceTimelineOut
from grag.storage.types import DocumentRecord


class DocumentOut(BaseModel):
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    metadata: dict[str, Any]
    graph_progress: dict[str, Any]
    graph_trace: TraceTimelineOut | None = None

    @staticmethod
    def from_document_record(
        d: DocumentRecord,
        graph_progress: dict[str, Any] | None = None,
        graph_trace: TraceTimelineOut | None = None,
    ) -> "DocumentOut":
        return DocumentOut(
            group_id=str(d.group_id),
            doc_id=str(d.doc_id),
            doc_name=str(d.doc_name),
            doc_time=str(d.doc_time),
            metadata=dict(d.metadata or {}),
            graph_progress=dict(graph_progress or {}),
            graph_trace=graph_trace,
        )
