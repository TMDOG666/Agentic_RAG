from __future__ import annotations

"""api.schemas.documents

文档相关 schema。

数据来源：
- `grag.storage.types.DocumentRecord`

说明：
- `DocumentRecord` 是 dataclass；API 层通过 `DocumentOut` 转为 JSON 友好的结构。
"""

from typing import Any

from pydantic import BaseModel

from grag.storage.types import DocumentRecord


class DocumentOut(BaseModel):
    """文档元信息输出结构。"""

    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    metadata: dict[str, Any]

    @staticmethod
    def from_document_record(d: DocumentRecord) -> "DocumentOut":
        """将内部 DocumentRecord 转换为 API schema。"""
        return DocumentOut(
            group_id=str(d.group_id),
            doc_id=str(d.doc_id),
            doc_name=str(d.doc_name),
            doc_time=str(d.doc_time),
            # metadata 在存储层为 Dict[str, Any]；这里强转为 dict 以确保可序列化。
            metadata=dict(d.metadata or {}),
        )
