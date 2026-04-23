from __future__ import annotations

import os
import tempfile
from typing import Optional

from fastapi import UploadFile

from api.schemas.ingest import IngestOut, IngestRetryIn, IngestTextIn
from api.services.documents_service import DocumentsService
from grag.config import get_config_manager
from grag.graph_construction.async_graph_service import AsyncGraphBuildService
from grag.graph_construction.graph_builder import GraphBuilder
from grag.preprocessing.document_processor import DocumentProcessor
from grag.storage.storage_impl import DataClientGraphStorage


class IngestService:
    """知识录入编排层。

    这里只负责把“输入来源 -> 基础入库 -> 图谱异步任务”串起来，
    不在这里混入图谱构建细节，方便后续继续拆 trace / checkpoint / replay。
    """

    def __init__(self) -> None:
        self._documents = DocumentsService()
        self._async_graph = AsyncGraphBuildService.instance()

    @staticmethod
    def _create_builder() -> GraphBuilder:
        return GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))

    @staticmethod
    def _reload_runtime_config() -> None:
        if not get_config_manager().reload_config():
            raise RuntimeError("重新加载 grag_config.yaml 失败")

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

    @staticmethod
    def _build_ingest_out(*, base, task) -> IngestOut:
        return IngestOut(
            group_id=base.document.group_id,
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

    def _build_retry_out(
        self,
        *,
        group_id: str,
        doc_id: str,
        task_id: str,
        task_status: str,
        task_stage: str,
    ) -> IngestOut:
        document = self._documents.get_document(group_id=group_id, doc_id=doc_id)
        chunks = self._documents.list_doc_chunks(group_id=group_id, doc_id=doc_id)
        if document is None:
            raise ValueError(f"文档不存在: group_id={group_id}, doc_id={doc_id}")
        return IngestOut(
            group_id=group_id,
            doc_id=document.doc_id,
            doc_name=document.doc_name,
            doc_time=document.doc_time,
            chunks=len(chunks),
            entities=0,
            relations=0,
            task_id=task_id,
            task_status=task_status,
            task_stage=task_stage,
        )

    def _submit_graph_build(
        self,
        *,
        text: str,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ):
        return self._async_graph.submit(
            text=text,
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
        )

    def _build_base_and_queue_graph(
        self,
        *,
        text: str,
        group_id: str,
        doc_name: str,
        doc_time: str,
        doc_id: Optional[str],
    ) -> IngestOut:
        # 文本录入和文件录入最终都会汇聚到同一条编排主线，
        # 这样后面补 trace / replay 时只需要维护一个入口。
        builder = self._create_builder()
        normalized_doc_id = self._cleanup_before_rebuild(group_id=group_id, doc_id=doc_id)
        base = builder.build_base_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=normalized_doc_id,
        )
        task = self._submit_graph_build(
            text=text,
            group_id=group_id,
            doc_id=base.document.doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
        )
        return self._build_ingest_out(base=base, task=task)

    @staticmethod
    def _extract_upload_text(file: UploadFile) -> tuple[str, str]:
        filename = str(getattr(file, "filename", "") or "upload")
        _, ext = os.path.splitext(filename)
        suffix = ext if ext else ".bin"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(file.file.read())

        try:
            processor = DocumentProcessor()
            text = processor.process_file(tmp_path, standardize=False)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return filename, text

    def ingest_text(self, payload: IngestTextIn) -> IngestOut:
        self._reload_runtime_config()
        return self._build_base_and_queue_graph(
            text=payload.text,
            group_id=payload.group_id,
            doc_name=payload.doc_name,
            doc_time=payload.doc_time,
            doc_id=payload.doc_id,
        )

    def retry_graph(self, payload: IngestRetryIn) -> IngestOut:
        self._reload_runtime_config()
        document = self._documents.get_document(group_id=payload.group_id, doc_id=payload.doc_id)
        if document is None:
            raise ValueError(f"文档不存在: group_id={payload.group_id}, doc_id={payload.doc_id}")

        text = self._documents.get_document_text(group_id=payload.group_id, doc_id=payload.doc_id)
        if not str(text or "").strip():
            raise ValueError("文档没有可用于重试的 chunk 文本，无法重跑 graph")

        self._documents.update_document_stage(
            group_id=payload.group_id,
            doc_id=payload.doc_id,
            ingest_stage="graph_retrying",
        )
        task = self._submit_graph_build(
            text=text,
            group_id=payload.group_id,
            doc_id=payload.doc_id,
            doc_name=document.doc_name,
            doc_time=document.doc_time,
        )
        return self._build_retry_out(
            group_id=payload.group_id,
            doc_id=payload.doc_id,
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
    ) -> IngestOut:
        self._reload_runtime_config()
        filename, text = self._extract_upload_text(file)
        return self._build_base_and_queue_graph(
            text=text,
            group_id=group_id,
            doc_name=filename,
            doc_time=doc_time,
            doc_id=doc_id,
        )
