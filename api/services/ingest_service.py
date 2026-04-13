from __future__ import annotations

import os
import tempfile
from typing import Optional

from fastapi import UploadFile

from api.schemas.ingest import IngestOut, IngestTextIn
from api.services.documents_service import DocumentsService
from grag.graph_construction.async_graph_service import AsyncGraphBuildService
from grag.graph_construction.graph_builder import GraphBuilder
from grag.preprocessing.document_processor import DocumentProcessor
from grag.storage.storage_impl import DataClientGraphStorage


class IngestService:
    def __init__(self) -> None:
        self._documents = DocumentsService()
        self._builder = GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))
        self._async_graph = AsyncGraphBuildService.instance()

    @staticmethod
    def _normalize_doc_id(doc_id: Optional[str]) -> Optional[str]:
        value = str(doc_id or "").strip()
        return value or None

    def _cleanup_before_rebuild(self, *, group_id: str, doc_id: Optional[str]) -> Optional[str]:
        normalized_doc_id = self._normalize_doc_id(doc_id)
        if not normalized_doc_id:
            return None
        existing = self._documents.get_document(group_id=group_id, doc_id=normalized_doc_id)
        if existing is not None:
            self._documents.delete_document(group_id=group_id, doc_id=normalized_doc_id)
        return normalized_doc_id

    def ingest_text(self, payload: IngestTextIn) -> IngestOut:
        doc_id = self._cleanup_before_rebuild(group_id=payload.group_id, doc_id=payload.doc_id)
        base = self._builder.build_base_and_save(
            text=payload.text,
            doc_time=payload.doc_time,
            doc_name=payload.doc_name,
            group_id=payload.group_id,
            doc_id=doc_id,
        )
        task = self._async_graph.submit(
            text=payload.text,
            group_id=payload.group_id,
            doc_id=base.document.doc_id,
            doc_name=payload.doc_name,
            doc_time=payload.doc_time,
        )
        return IngestOut(
            group_id=payload.group_id,
            doc_id=base.document.doc_id,
            doc_name=base.document.doc_name,
            doc_time=base.document.doc_time,
            chunks=len(base.chunks or []),
            entities=0,
            relations=0,
            task_id=task.task_id,
            task_status=task.status,
            task_stage=task.stage,
        )

    def ingest_upload(
        self,
        *,
        group_id: str,
        doc_time: str,
        file: UploadFile,
        doc_id: Optional[str],
        standardize: bool,
    ) -> IngestOut:
        filename = str(getattr(file, "filename", "") or "upload")
        _, ext = os.path.splitext(filename)
        suffix = ext if ext else ".bin"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(file.file.read())

        try:
            processor = DocumentProcessor()
            text = processor.process_file(tmp_path, standardize=bool(standardize))
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        normalized_doc_id = self._cleanup_before_rebuild(group_id=group_id, doc_id=doc_id)
        base = self._builder.build_base_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=filename,
            group_id=group_id,
            doc_id=normalized_doc_id,
        )
        task = self._async_graph.submit(
            text=text,
            group_id=group_id,
            doc_id=base.document.doc_id,
            doc_name=filename,
            doc_time=doc_time,
        )
        return IngestOut(
            group_id=group_id,
            doc_id=base.document.doc_id,
            doc_name=base.document.doc_name,
            doc_time=base.document.doc_time,
            chunks=len(base.chunks or []),
            entities=0,
            relations=0,
            task_id=task.task_id,
            task_status=task.status,
            task_stage=task.stage,
        )
