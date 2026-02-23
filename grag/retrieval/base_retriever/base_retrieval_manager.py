"""grag.retrieval.base_retriever.base_retrieval_manager

基础层检索入口（BaseRetrievalManager）。

定位：
- 该模块属于基础检索层（base_retriever）。
- 只负责“基础检索能力”的编排与结果聚合（不做策略融合）。

基础模式（直接召回）：
- keyword / semantic / graph

扩展模式（仍属于基础能力范围）：
- vector：semantic 的别名（对齐“向量检索”叫法）
- local / global：LightRAG 风格的图检索入口拆分（规则 high/low -> graph）

更高层的策略融合：
- 例如 native/local/global 的“组合检索策略”（自动组合 keyword + vector + local/global）
  建议放在 `grag/retrieval/advanced_retrieval_manager.py`。
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

from grag.data_client import get_data_manager
from grag.model.embedding_client import EmbeddingClient
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository

from .keyword_retriever import KeywordRetriever, KeywordChunkHit
from .semantic_retriever import SemanticRetriever, SemanticChunkHit
from .graph_retriever import GraphRetriever, GraphSubgraphResult
from ..utils.query_decomposition import split_high_low
from ..utils.reranker import rerank_chunk_hits, rerank_graph_nodes


RetrievalMode = Literal["keyword", "semantic", "vector", "graph", "local", "global"]


@dataclass(frozen=True)
class RetrievalResult:
    keyword_hits: list[KeywordChunkHit]
    semantic_hits: list[SemanticChunkHit]
    graph: Optional[GraphSubgraphResult]
    local_graph: Optional[GraphSubgraphResult] = None
    global_graph: Optional[GraphSubgraphResult] = None


class BaseRetrievalManager:
    def __init__(
        self,
        *,
        embedding_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> None:
        self._keyword = KeywordRetriever()
        self._semantic = SemanticRetriever(
            embedding_provider=embedding_provider,
            milvus_collection_name=milvus_collection_name,
        )
        self._graph = GraphRetriever()

        # graph_index（entity/relation embeddings）相关依赖：
        # - 该 collection 独立于 chunk embeddings（SemanticRetriever 使用的 collection）。
        # - BaseRetrievalManager 只需要：
        #   1) 将 query 向量化
        #   2) 在 graph_index 中做 ANN 召回
        #   3) 用召回到的实体/关系端点作为 Neo4j 扩图起点
        dm = get_data_manager()
        self._graph_index_repo = MilvusGraphIndexRepository(
            dm.get_milvus_client(),
            collection_name=str(milvus_graph_index_collection_name or "grag_graph_index"),
        )
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)

    @staticmethod
    def _merge_subgraphs(subgraphs: list[GraphSubgraphResult]) -> GraphSubgraphResult:
        """将多个子图结果合并为一个子图。

        说明：
        - GraphRetriever.search 返回的 nodes/edges 是 list[dict]。
        - 不同起点扩图可能产生重复节点/边，因此这里做去重合并。
        - 去重 key 尽量使用稳定字段；字段缺失时退化为 repr(dict)（仍可工作但不保证最优）。
        """

        nodes_by_key: dict[str, dict] = {}
        edges_by_key: dict[str, dict] = {}

        def _node_key(n: dict) -> str:
            labels = n.get("labels")
            return f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name') or ''}"

        def _edge_key(e: dict) -> str:
            # 当前 neo4j_repository.search_entity_subgraph 返回的 edge dict 不包含起止点。
            # 因此只能按 (group_id, doc_id, type, description, confidence) 去重。
            return f"{e.get('group_id')}:{e.get('doc_id')}:{e.get('type')}:{e.get('description')}:{e.get('confidence')}"

        for sg in subgraphs:
            for n in sg.nodes or []:
                try:
                    k = _node_key(n)
                except Exception:
                    k = repr(n)
                nodes_by_key.setdefault(k, n)

            for e in sg.edges or []:
                try:
                    k = _edge_key(e)
                except Exception:
                    k = repr(e)
                edges_by_key.setdefault(k, e)

        return GraphSubgraphResult(nodes=list(nodes_by_key.values()), edges=list(edges_by_key.values()))

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
        local_graph_res: Optional[GraphSubgraphResult] = None
        global_graph_res: Optional[GraphSubgraphResult] = None

        normalized_modes: set[str] = set([str(m).strip().lower() for m in (modes or []) if str(m).strip()])
        if "vector" in normalized_modes:
            normalized_modes.add("semantic")

        if "keyword" in normalized_modes:
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

        if "semantic" in normalized_modes:
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

        if "graph" in normalized_modes:
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

        if "local" in normalized_modes:
            # LightRAG 风格 local：低层关键词 -> entity 向量召回 -> 以命中实体作为图扩展起点。
            #
            # 约定：
            # - low-level 关键词默认来自 split_high_low(query) 的 low。
            # - 如果调用方显式传入 graph_entity_name（例如 "A>B"），则也参与拆分与兜底。
            #
            # 注意：
            # - 这里不再直接用 low 作为 Neo4j 的 entity_name，而是先走 Milvus graph_index(entity)。
            # - 如果 graph_index 没有数据或召回为空，会退化为“直接用 low 做图检索”。
            high, low = split_high_low(query)
            _, low_from_entity = split_high_low(graph_entity_name or "")
            local_key = low or low_from_entity or (graph_entity_name or query)

            subgraphs: list[GraphSubgraphResult] = []

            try:
                qv = self._embedding_client.embed_texts([str(local_key)])[0]
                hits = self._graph_index_repo.search(
                    group_id=group_id,
                    kind="entity",
                    query_vector=qv,
                    top_k=max(3, min(10, int(top_k))),
                    doc_id=doc_id,
                    output_fields=["name", "doc_id", "group_id", "source_id", "pk"],
                )
                entity_names = []
                seen_names: set[str] = set()
                for h in hits or []:
                    nm = str(h.get("name") or "").strip()
                    if not nm or nm in seen_names:
                        continue
                    seen_names.add(nm)
                    entity_names.append(nm)

                for nm in entity_names:
                    subgraphs.append(
                        self._graph.search(
                            group_id=group_id,
                            entity_name=nm,
                            max_depth=int(graph_max_depth),
                            limit=int(graph_limit),
                            doc_id=doc_id,
                        )
                    )
            except Exception:
                # graph_index 召回失败时，退化到旧逻辑（直接用 local_key 扩图）。
                subgraphs = []

            if not subgraphs:
                local_graph_res = self._graph.search(
                    group_id=group_id,
                    entity_name=str(local_key),
                    max_depth=int(graph_max_depth),
                    limit=int(graph_limit),
                    doc_id=doc_id,
                )
            else:
                local_graph_res = self._merge_subgraphs(subgraphs)

            if rerank_enabled and local_graph_res and local_graph_res.nodes:
                nodes, _ = rerank_graph_nodes(
                    query=query,
                    nodes=local_graph_res.nodes,
                    top_k=None,
                    provider_name=rerank_provider,
                )
                local_graph_res = GraphSubgraphResult(nodes=nodes, edges=local_graph_res.edges)

        if "global" in normalized_modes:
            # LightRAG 风格 global：高层关键词 -> relation 向量召回 -> 取 head/tail 作为扩图起点。
            high, _ = split_high_low(query)
            high_from_entity, _ = split_high_low(graph_entity_name or "")
            global_key = high or high_from_entity or (graph_entity_name or query)

            subgraphs: list[GraphSubgraphResult] = []

            try:
                qv = self._embedding_client.embed_texts([str(global_key)])[0]
                hits = self._graph_index_repo.search(
                    group_id=group_id,
                    kind="relation",
                    query_vector=qv,
                    top_k=max(3, min(10, int(top_k))),
                    doc_id=doc_id,
                    output_fields=["head_name", "tail_name", "relation_type", "doc_id", "group_id", "source_id", "pk"],
                )

                start_entities: list[str] = []
                seen: set[str] = set()
                for h in hits or []:
                    for nm in [h.get("head_name"), h.get("tail_name")]:
                        s = str(nm or "").strip()
                        if not s or s in seen:
                            continue
                        seen.add(s)
                        start_entities.append(s)

                for nm in start_entities:
                    subgraphs.append(
                        self._graph.search(
                            group_id=group_id,
                            entity_name=nm,
                            max_depth=int(graph_max_depth),
                            limit=int(graph_limit),
                            doc_id=doc_id,
                        )
                    )
            except Exception:
                subgraphs = []

            if not subgraphs:
                global_graph_res = self._graph.search(
                    group_id=group_id,
                    entity_name=str(global_key),
                    max_depth=int(graph_max_depth),
                    limit=int(graph_limit),
                    doc_id=doc_id,
                )
            else:
                global_graph_res = self._merge_subgraphs(subgraphs)

            if rerank_enabled and global_graph_res and global_graph_res.nodes:
                nodes, _ = rerank_graph_nodes(
                    query=query,
                    nodes=global_graph_res.nodes,
                    top_k=None,
                    provider_name=rerank_provider,
                )
                global_graph_res = GraphSubgraphResult(nodes=nodes, edges=global_graph_res.edges)

        return RetrievalResult(
            keyword_hits=keyword_hits,
            semantic_hits=semantic_hits,
            graph=graph_res or local_graph_res or global_graph_res,
            local_graph=local_graph_res,
            global_graph=global_graph_res,
        )
