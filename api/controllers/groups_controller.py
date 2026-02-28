from __future__ import annotations

"""api.controllers.groups_controller

Group 查询类接口（只读）。

这些接口主要用于：
- 展示当前系统已有的 group 列表
- 查看某个 group 下的文档元信息
- 查看某个 group 的图谱（Neo4j nodes/edges）

说明：
- group 的“增删”在 `groups_admin_controller` 中实现。
"""

from fastapi import APIRouter

from api.schemas.documents import DocumentOut
from api.schemas.graph import GraphOut
from api.schemas.groups import GroupOut
from api.services.groups_service import GroupsService

router = APIRouter()


@router.get("")
def list_groups(limit: int = 500) -> list[GroupOut]:
    """列出 group 列表。

    Args:
        limit: 最大返回条数。

    Returns:
        list[GroupOut]: group_id 列表。
    """
    svc = GroupsService()
    return [GroupOut(group_id=g) for g in svc.list_groups(limit=limit)]


@router.get("/{group_id}/documents")
def list_group_documents(
    group_id: str,
    limit: int = 200,
    doc_time_start: str | None = None,
    doc_time_end: str | None = None,
) -> list[DocumentOut]:
    """列出 group 下的文档元信息。

    Args:
        group_id: 组 ID。
        limit: 最大返回条数。
        doc_time_start/doc_time_end: 可选时间范围过滤（字符串比较语义，建议 ISO8601）。
    """
    svc = GroupsService()
    docs = svc.list_group_documents(
        group_id=group_id,
        limit=limit,
        doc_time_start=doc_time_start,
        doc_time_end=doc_time_end,
    )
    return [DocumentOut.from_document_record(d) for d in docs]


@router.get("/{group_id}/graph")
def get_group_graph(
    group_id: str,
    limit: int = 200,
    doc_id: str | None = None,
) -> GraphOut:
    """获取 group 的图谱（nodes/edges）。

    说明：
    - 数据来自 Neo4j。
    - 可选 `doc_id`：只看某一个文档对应的子图。
    """
    svc = GroupsService()
    g = svc.get_group_graph(group_id=group_id, limit=limit, doc_id=doc_id)
    return GraphOut(nodes=list(g.get("nodes") or []), edges=list(g.get("edges") or []))
