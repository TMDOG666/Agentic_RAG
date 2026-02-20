"""grag.retrieval.base_retriever.base_retrieval_manager

基础层检索入口（BaseRetrievalManager）。

定位：
- 该模块属于基础检索层（base_retriever）。
- 只负责编排三种基础检索能力：keyword / semantic / graph。
- 可选地对召回结果执行重排序（rerank）：
  - keyword/semantic：对 chunk hits 重排序
  - graph：对子图 nodes 重排序（edges 不变）

注意：
- `group_id` 为必填参数，用于数据隔离。
- 本模块不负责融合检索/组合检索；更高层的策略建议放在 grag/retrieval/ 下。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .keyword_retriever import KeywordRetriever, KeywordChunkHit
from .semantic_retriever import SemanticRetriever, SemanticChunkHit
from .graph_retriever import GraphRetriever, GraphSubgraphResult
from ..reranker import rerank_chunk_hits, rerank_graph_nodes


RetrievalMode = Literal["keyword", "semantic", "graph"]


@dataclass(frozen=True)
class RetrievalResult:
    keyword_hits: list[KeywordChunkHit]
    semantic_hits: list[SemanticChunkHit]
    graph: Optional[GraphSubgraphResult]


class BaseRetrievalManager:
    def __init__(
        self,
        *,
        embedding_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
    ) -> None:
        self._keyword = KeywordRetriever()
        self._semantic = SemanticRetriever(
            embedding_provider=embedding_provider,
            milvus_collection_name=milvus_collection_name,
        )
        self._graph = GraphRetriever()

    def search(
        self,
        *,
        group_id: str,
        query: str,
        modes: list[RetrievalMode],
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
        graph_entity_name: Optional[str] = None,
        graph_max_depth: int = 2,
        graph_limit: int = 50,
    ) -> RetrievalResult:
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        keyword_hits: list[KeywordChunkHit] = []
        semantic_hits: list[SemanticChunkHit] = []
        graph_res: Optional[GraphSubgraphResult] = None

        if "keyword" in modes:
            keyword_hits = self._keyword.search(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                doc_time_start=doc_time_start,
                doc_time_end=doc_time_end,
            )

            if rerank_enabled and keyword_hits:
                keyword_hits, _ = rerank_chunk_hits(
                    query=query,
                    hits=keyword_hits,
                    top_k=int(top_k),
                    provider_name=rerank_provider,
                )

        if "semantic" in modes:
            semantic_hits = self._semantic.search(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                doc_time_start=doc_time_start,
                doc_time_end=doc_time_end,
            )

            if rerank_enabled and semantic_hits:
                semantic_hits, _ = rerank_chunk_hits(
                    query=query,
                    hits=semantic_hits,
                    top_k=int(top_k),
                    provider_name=rerank_provider,
                )

        if "graph" in modes:
            name = graph_entity_name or query
            graph_res = self._graph.search(
                group_id=group_id,
                entity_name=name,
                max_depth=int(graph_max_depth),
                limit=int(graph_limit),
                doc_id=doc_id,
            )

            if rerank_enabled and graph_res and graph_res.nodes:
                nodes, _ = rerank_graph_nodes(
                    query=query,
                    nodes=graph_res.nodes,
                    top_k=None,
                    provider_name=rerank_provider,
                )
                graph_res = GraphSubgraphResult(nodes=nodes, edges=graph_res.edges)

        return RetrievalResult(
            keyword_hits=keyword_hits,
            semantic_hits=semantic_hits,
            graph=graph_res,
        )
