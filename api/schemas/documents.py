from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from grag.storage.types import DocumentRecord


class DocumentOut(BaseModel):
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    metadata: dict[str, Any]
    graph_progress: dict[str, Any]

    @staticmethod
    def from_document_record(
        d: DocumentRecord,
        graph_progress: dict[str, Any] | None = None,
    ) -> "DocumentOut":
        return DocumentOut(
            group_id=str(d.group_id),
            doc_id=str(d.doc_id),
            doc_name=str(d.doc_name),
            doc_time=str(d.doc_time),
            metadata=dict(d.metadata or {}),
            graph_progress=dict(graph_progress or {}),
        )
