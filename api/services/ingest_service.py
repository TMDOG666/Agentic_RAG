from __future__ import annotations

"""api.services.ingest_service

IngestService：知识录入业务层。

两类入口：
- ingest_text：直接录入纯文本
- ingest_upload：上传文件 -> 解析为文本 -> 录入

解析策略：
- 先将 UploadFile 落盘为临时文件（DocumentProcessor 以文件路径为入口）
- 解析完成后删除临时文件（best-effort）
"""

import os
import tempfile
from typing import Optional

from fastapi import UploadFile

from grag.entrypoint import GRAG
from grag.preprocessing.document_processor import DocumentProcessor

from api.schemas.ingest import IngestOut, IngestTextIn


class IngestService:
    """知识录入服务（对 GRAG.build_kg 的封装）。"""

    def __init__(self) -> None:
        # GRAG facade：封装了构建流程（chunk/embedding/graph fusion/存储写入）。
        self._grag = GRAG()

    def ingest_text(self, payload: IngestTextIn) -> IngestOut:
        """录入纯文本并触发构建。"""
        r = self._grag.build_kg(
            text=payload.text,
            doc_time=payload.doc_time,
            doc_name=payload.doc_name,
            group_id=payload.group_id,
            doc_id=payload.doc_id,
        )
        return IngestOut(
            group_id=payload.group_id,
            doc_id=r.document.doc_id,
            doc_name=r.document.doc_name,
            doc_time=r.document.doc_time,
            chunks=len(r.chunks or []),
            entities=len(r.entities or []),
            relations=len(r.relations or []),
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
        """上传文件并录入。

        Args:
            group_id/doc_time/doc_id: 构建过程的业务主键与时间。
            file: FastAPI UploadFile。
            standardize: 是否使用 LLM 标准化解析出来的文本。
        """
        filename = str(getattr(file, "filename", "") or "upload")
        _, ext = os.path.splitext(filename)
        suffix = ext if ext else ".bin"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            # 读取上传内容并写入临时文件。
            tmp.write(file.file.read())

        try:
            processor = DocumentProcessor()
            # DocumentProcessor 会根据文件后缀自动选择解析方式。
            text = processor.process_file(tmp_path, standardize=bool(standardize))
        finally:
            try:
                # best-effort 删除临时文件；失败不影响主流程。
                os.remove(tmp_path)
            except Exception:
                pass

        r = self._grag.build_kg(
            text=text,
            doc_time=doc_time,
            doc_name=filename,
            group_id=group_id,
            doc_id=doc_id,
        )
        return IngestOut(
            group_id=group_id,
            doc_id=r.document.doc_id,
            doc_name=r.document.doc_name,
            doc_time=r.document.doc_time,
            chunks=len(r.chunks or []),
            entities=len(r.entities or []),
            relations=len(r.relations or []),
        )
