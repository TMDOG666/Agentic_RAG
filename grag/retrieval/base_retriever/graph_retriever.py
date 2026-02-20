"""grag.retrieval.graph_retriever

图检索（Graph Retrieval）：
- 在 Neo4j 中按实体名/别名检索起点实体
- 从该实体出发扩展一定跳数（max_depth）的关系子图

返回值为子图结构（nodes/edges），不属于 chunk 召回，因此当前不做重排序。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from grag.data_client import get_data_manager
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository


@dataclass(frozen=True)
class GraphSubgraphResult:
    """图检索结果结构"""
    nodes: list[dict]
    edges: list[dict]


class GraphRetriever:
    """图检索器"""
    def __init__(self) -> None:
        # 图检索走 Neo4j。
        dm = get_data_manager()
        self._neo4j_repo = Neo4jGraphRepository(dm.get_neo4j_client())

    def search(
        self,
        *,
        group_id: str,
        entity_name: str,
        max_depth: int = 2,
        limit: int = 50,
        doc_id: Optional[str] = None,
    ) -> GraphSubgraphResult:
        """执行图检索。

        Args:
            group_id: 必填，数据隔离维度。
            entity_name: 实体名（或别名）。
            max_depth: 关系扩展的最大跳数。
            limit: 返回路径/关系上限（具体含义取决于底层 cypher 实现）。
            doc_id: 可选，只在指定 doc 内检索/扩展。

        Returns:
            GraphSubgraphResult(nodes=[...], edges=[...])
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(entity_name or "").strip():
            return GraphSubgraphResult(nodes=[], edges=[])

        # Neo4jRepository 负责 Cypher 细节，这里只负责参数透传与返回结构整理。
        data = self._neo4j_repo.search_entity_subgraph(
            group_id=group_id,
            entity_name=entity_name,
            max_depth=int(max_depth),
            limit=int(limit),
            doc_id=doc_id,
        )

        return GraphSubgraphResult(
            nodes=list(data.get("nodes") or []),
            edges=list(data.get("edges") or []),
        )