from __future__ import annotations

"""api.controllers.documents_controller

文档（Document）查询与删除接口。

说明：
- 文档的“创建/写入”来自 `/ingest`（会调用 GRAG.build_kg）。
- 本 controller 主要用于查看与删除已入库文档。

删除语义（doc 级）：
- 会级联清理：
  - Postgres: documents/chunks/entities/relations
  - Milvus: chunk embeddings
  - Milvus graph_index: entity/relation embeddings
  - Neo4j: 图节点与边
"""

from fastapi import APIRouter

from api.schemas.documents import DocumentOut
from api.services.documents_service import DocumentsService

router = APIRouter()


@router.get("")
def list_documents(group_id: str, limit: int = 200) -> list[DocumentOut]:
    """列出某个 group 下的文档列表（按时间倒序）。"""
    svc = DocumentsService()
    docs = svc.list_documents(group_id=group_id, limit=limit)
    return [DocumentOut.from_document_record(d) for d in docs]


@router.get("/{doc_id}")
def get_document(group_id: str, doc_id: str) -> DocumentOut | None:
    """按 doc_id 获取文档元信息。"""
    svc = DocumentsService()
    d = svc.get_document(group_id=group_id, doc_id=doc_id)
    return DocumentOut.from_document_record(d) if d is not None else None


@router.delete("/{doc_id}")
def delete_document(group_id: str, doc_id: str) -> dict:
    """删除某个文档及其所有派生资产（doc 级级联删除）。"""
    svc = DocumentsService()
    svc.delete_document(group_id=group_id, doc_id=doc_id)
    return {"deleted": True}
