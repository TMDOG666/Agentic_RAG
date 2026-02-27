"""grag.retrieval.advanced_retrieval_manager

高级检索入口（AdvancedRetrievalManager）。

定位：
- 该模块位于 `grag/retrieval/`（高层策略层），用于对外提供更“产品化”的检索入口。
- 底层的 `BaseRetrievalManager` 提供原子能力（chunk keyword/vector、entity/relation vector 等）。

说明：
- 旧版本包含 LightRAG 风格的 local/global（依赖 query decomposition 与扩图策略）。
- 当前实现已移除该模式，仅保留更灵活的“检索范式”接口，便于上层/agent 自由编排。
"""

from __future__ import annotations

from typing import Optional

from grag.retrieval.base_retriever.base_retrieval_manager import (
    BaseRetrievalManager,
    RetrievalResult,
)
from grag.retrieval.utils.reranker import rerank_chunk_hits, rerank_dict_hits


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

    def chunks_vector(
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
        """文本块检索模式（向量检索）。"""
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

    def chunks_keyword(
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
        """文本块检索模式（关键词检索）。"""
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

    def entities(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        output_fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """实体检索模式（graph_index: kind=entity）。

        返回：Milvus graph_index 命中记录（list[dict]），包含 output_fields + score。
        """
        self._require_group_id(group_id)
        hits = self._base.search_entities_vector(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            output_fields=output_fields,
        )
        if rerank_enabled and hits:
            hits, _ = rerank_dict_hits(
                query=query,
                hits=hits,
                top_k=int(top_k),
                provider_name=rerank_provider,
            )
        return list(hits or [])

    def relations_by_entities(
        self,
        *,
        group_id: str,
        entity_names: list[str],
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        self._require_group_id(group_id)
        return self._base.search_relations_by_entities(
            group_id=group_id,
            entity_names=list(entity_names or []),
            limit=int(limit),
            doc_id=doc_id,
        )

    def entities_by_relations(
        self,
        *,
        group_id: str,
        relation_ids: Optional[list[str]] = None,
        relation_triples: Optional[list[dict]] = None,
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        self._require_group_id(group_id)
        return self._base.search_entities_by_relations(
            group_id=group_id,
            relation_ids=list(relation_ids or []) if relation_ids is not None else None,
            relation_triples=list(relation_triples or []) if relation_triples is not None else None,
            limit=int(limit),
            doc_id=doc_id,
        )

    def relations(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        rerank_enabled: bool = False,
        rerank_provider: Optional[str] = None,
        doc_id: Optional[str] = None,
        output_fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """关系检索模式（graph_index: kind=relation）。

        返回：Milvus graph_index 命中记录（list[dict]），常见字段包含：
        - head_name / tail_name / relation_type / pk / source_id / score
        """
        self._require_group_id(group_id)
        hits = self._base.search_relations_vector(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            output_fields=output_fields,
        )
        if rerank_enabled and hits:
            hits, _ = rerank_dict_hits(
                query=query,
                hits=hits,
                top_k=int(top_k),
                provider_name=rerank_provider,
            )
        return list(hits or [])
