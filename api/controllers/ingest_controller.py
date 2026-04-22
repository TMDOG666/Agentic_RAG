from __future__ import annotations

"""api.controllers.ingest_controller

知识录入（Ingestion）接口。

目标：
- 将不同来源的数据（纯文本/上传文件）统一转成文本
- 调用 GRAG 的构建入口 `build_kg` 进行 chunking/embedding/实体关系抽取/融合，并落库

说明：
- 文件解析能力由 `grag.preprocessing.document_processor.DocumentProcessor` 提供
- `standardize=True` 时会用 LLM 做文本标准化（成本更高，但通常质量更好）
"""

from fastapi import APIRouter, File, UploadFile

from api.schemas.ingest import IngestRetryIn, IngestTextIn, IngestOut
from api.services.ingest_service import IngestService

router = APIRouter()


@router.post("/text")
def ingest_text(payload: IngestTextIn) -> IngestOut:
    """录入纯文本。

    Args:
        payload: group_id/doc_time/doc_name/text/doc_id(可选)

    Returns:
        IngestOut: 落库后的 doc_id + 统计信息。
    """
    svc = IngestService()
    return svc.ingest_text(payload)


@router.post("/upload")
def ingest_upload(
    group_id: str,
    doc_time: str,
    file: UploadFile = File(...),
    doc_id: str | None = None,
) -> IngestOut:
    """上传文件并录入。

    FastAPI 会以 multipart/form-data 方式上传文件。

    Args:
        group_id: 组 ID。
        doc_time: 文档时间（建议 ISO8601 字符串）。
        file: 上传文件。
        doc_id: 可选；不传则由构建流程生成。
        standardize: 是否调用 LLM 标准化解析结果。
    """
    svc = IngestService()
    return svc.ingest_upload(
        group_id=group_id,
        doc_time=doc_time,
        file=file,
        doc_id=doc_id,
    )


@router.post("/retry-graph")
def retry_graph(payload: IngestRetryIn) -> IngestOut:
    svc = IngestService()
    return svc.retry_graph(payload)
