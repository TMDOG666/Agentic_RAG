from __future__ import annotations

"""api.schemas.ingest

知识录入（ingest）相关 schema。

说明：
- ingest_text：使用 IngestTextIn
- ingest_upload：使用 query/form 参数，因此不需要单独的上传 schema
"""

from typing import Optional

from pydantic import BaseModel


class IngestTextIn(BaseModel):
    """纯文本录入入参。"""
    group_id: str
    doc_time: str
    doc_name: str
    text: str
    doc_id: Optional[str] = None


class IngestOut(BaseModel):
    """录入后的返回结构（包含资产统计）。"""
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    chunks: int
    entities: int
    relations: int
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_stage: Optional[str] = None


class IngestRetryIn(BaseModel):
    group_id: str
    doc_id: str
