from __future__ import annotations

"""api.schemas.retrieval

检索接口 schema。

核心思想：
- 用一个统一的 endpoint（POST /retrieval）承载多个检索模式。
- 通过 `mode` 字段选择具体能力。

注意：
- 不同 mode 需要的字段不同；当前用“可选字段 + mode 控制”的方式简化 MVP。
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


RetrievalMode = Literal[
    "chunks_vector",
    "chunks_keyword",
    "entities",
    "relations",
    "relations_by_entities",
    "entities_by_relations",
]


class RetrievalRequest(BaseModel):
    """检索入参。"""

    # group_id 是强制隔离维度：避免跨 group 检索导致的数据污染。
    group_id: str
    mode: RetrievalMode

    # query：多数模式都会用到（chunks_vector/chunks_keyword/entities/relations）。
    query: Optional[str] = None
    top_k: Optional[int] = Field(default=20)

    doc_id: Optional[str] = None
    doc_time_start: Optional[str] = None
    doc_time_end: Optional[str] = None

    rerank_enabled: Optional[bool] = None
    rerank_provider: Optional[str] = None

    output_fields: Optional[list[str]] = None

    # graph primitives
    # relations_by_entities：需要 entity_names
    entity_names: Optional[list[str]] = None

    # entities_by_relations：可按 relation_id 或 relation_triples 扩展
    relation_ids: Optional[list[str]] = None
    relation_triples: Optional[list[dict[str, Any]]] = None

    limit: Optional[int] = None


class RetrievalResponse(BaseModel):
    """检索出参。

    为了兼容不同 mode 的返回结构，统一包一层 `result: dict`。
    """
    result: dict[str, Any]
