"""grag.retrieval.advanced_retrieval_manager

高级检索入口（AdvancedRetrievalManager）。

定位：
- 该模块位于 `grag/retrieval/`（高层策略层），用于实现“更贴近产品/LightRAG 用法”的检索模式。
- 底层的 `BaseRetrievalManager` 只负责基础能力编排（keyword/semantic/graph + rerank），不负责策略融合。

当前支持的高级模式：
- native: “向量检索（native）”，等价于 semantic 召回（embedding + Milvus）。
- local: LightRAG 风格的 local 子图检索入口（低层实体为入口），通常会组合 keyword + vector(native) + local graph。
- global: LightRAG 风格的 global 子图检索入口（高层主题为入口），通常会组合 keyword + vector(native) + global graph。

设计原则：
- 对外保持 `search()` 签名与旧 RetrievalManager 基本一致，尽量兼容既有调用。
- 高级模式只是“展开/组合 modes”并调用 BaseRetrievalManager，不改变底层检索算法。
"""

from __future__ import annotations

from typing import Optional

from grag.retrieval.base_retriever.base_retrieval_manager import (
    BaseRetrievalManager,
    RetrievalResult,
)
from grag.retrieval.base_retriever.graph_retriever import GraphSubgraphResult
from grag.retrieval.utils.query_decomposition import split_high_low
from grag.retrieval.utils.reranker import rerank_chunk_hits, rerank_graph_nodes


class AdvancedRetrievalManager:
    def __init__(
        self,
        *,
        embedding_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> None:
        self._base = BaseRetrievalManager(
            embedding_provider=embedding_provider,
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )

    @staticmethod
    def _require_group_id(group_id: str) -> None:
        if not str(group_id or "").strip():
            raise ValueError("group_id is required")

    def _search_local(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int,
        doc_id: Optional[str],
        graph_entity_name: Optional[str],
        graph_max_depth: int,
        graph_limit: int,
    ) -> GraphSubgraphResult:
        low_from_param = []
        if graph_entity_name and "," in str(graph_entity_name):
            low_from_param = [s.strip() for s in str(graph_entity_name).split(",") if s.strip()]

        if low_from_param:
            low_keywords = low_from_param
        else:
            _, low = split_high_low(query)
            low_keywords = [low] if str(low or "").strip() else []

        seeds: list[str] = []
        for kw in low_keywords or []:
            hits = self._base.search_entities_vector(
                group_id=group_id,
                query=str(kw),
                top_k=max(3, min(10, int(top_k))),
                doc_id=doc_id,
                output_fields=["name", "pk", "doc_id", "group_id", "source_id"],
            )
            for h in hits or []:
                nm = str(h.get("name") or "").strip()
                if nm:
                    seeds.append(nm)

        return self._base.expand_graph_by_entities(
            group_id=group_id,
            entity_names=seeds,
            max_depth=int(graph_max_depth),
            limit=int(graph_limit),
            doc_id=doc_id,
        )

    def _search_global(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int,
        doc_id: Optional[str],
        graph_entity_name: Optional[str],
        graph_max_depth: int,
        graph_limit: int,
    ) -> Optional[dict]:
        high_from_param = []
        if graph_entity_name and "," in str(graph_entity_name):
            high_from_param = [s.strip() for s in str(graph_entity_name).split(",") if s.strip()]

        if high_from_param:
            high_keywords = high_from_param
        else:
            high, _ = split_high_low(query)
            high_keywords = [high] if str(high or "").strip() else []

        triples: list[dict] = []
        for kw in high_keywords or []:
            hits = self._base.search_relations_vector(
                group_id=group_id,
                query=str(kw),
                top_k=max(3, min(10, int(top_k))),
                doc_id=doc_id,
                output_fields=["head_name", "tail_name", "relation_type", "pk", "doc_id", "group_id"],
            )
            triples.extend(list(hits or []))

        return self._base.expand_graph_by_triples(
            group_id=group_id,
            triples=triples,
            max_depth=int(graph_max_depth),
            limit=int(graph_limit),
            doc_id=doc_id,
        )

    def native(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> RetrievalResult:
        self._require_group_id(group_id)
        semantic_hits = self._base.search_chunks_vector(
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
        return RetrievalResult(
            keyword_hits=[],
            semantic_hits=list(semantic_hits or []),
            graph=None,
            local_graph=None,
            global_graph=None,
        )

    def keyword(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> RetrievalResult:
        self._require_group_id(group_id)
        keyword_hits = self._base.search_chunks_keyword(
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
        return RetrievalResult(
            keyword_hits=list(keyword_hits or []),
            semantic_hits=[],
            graph=None,
            local_graph=None,
            global_graph=None,
        )

    def local(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        graph_entity_name: Optional[str] = None,
        graph_max_depth: int = 2,
        graph_limit: int = 50,
    ) -> RetrievalResult:
        self._require_group_id(group_id)
        local_graph_res = self._search_local(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            graph_entity_name=graph_entity_name,
            graph_max_depth=int(graph_max_depth),
            graph_limit=int(graph_limit),
        )
        if rerank_enabled and local_graph_res.nodes:
            nodes, _ = rerank_graph_nodes(
                query=query,
                nodes=list(local_graph_res.nodes or []),
                top_k=None,
                provider_name=rerank_provider,
            )
            local_graph_res = GraphSubgraphResult(nodes=nodes, edges=list(local_graph_res.edges or []))
        return RetrievalResult(
            keyword_hits=[],
            semantic_hits=[],
            graph=local_graph_res,
            local_graph=local_graph_res,
            global_graph=None,
        )

    def global_(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        graph_entity_name: Optional[str] = None,
        graph_max_depth: int = 2,
        graph_limit: int = 50,
    ) -> RetrievalResult:
        self._require_group_id(group_id)
        global_graph_res = self._search_global(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            graph_entity_name=graph_entity_name,
            graph_max_depth=int(graph_max_depth),
            graph_limit=int(graph_limit),
        )
        if rerank_enabled and global_graph_res.nodes:
            nodes, _ = rerank_graph_nodes(
                query=query,
                nodes=list(global_graph_res.nodes or []),
                top_k=None,
                provider_name=rerank_provider,
            )
            global_graph_res = GraphSubgraphResult(nodes=nodes, edges=list(global_graph_res.edges or []))
        return RetrievalResult(
            keyword_hits=[],
            semantic_hits=[],
            graph=global_graph_res,
            local_graph=None,
            global_graph=global_graph_res,
        )
