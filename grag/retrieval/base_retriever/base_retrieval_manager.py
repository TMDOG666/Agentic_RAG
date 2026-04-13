"""grag.retrieval.base_retriever.base_retrieval_manager

BaseRetrievalManager（基础检索原子能力层）。

定位：
- 该模块属于基础检索层（base_retriever）。
- 只提供“原子/可组合”的检索 primitives；不包含任何 modes/策略编排。

本模块提供的 primitives（全部是“单一职责、可组合”的能力）：
- Chunk 检索：
  - `search_chunks_vector`：向量召回 chunk（embedding + Milvus），返回 `SemanticChunkHit`
  - `search_chunks_keyword`：关键字召回 chunk（Postgres ILIKE 等），返回 `KeywordChunkHit`
- GraphIndex（Milvus）检索：
  - `search_entities_vector`：在 graph_index(kind=entity) 中向量召回实体
  - `search_relations_vector`：在 graph_index(kind=relation) 中向量召回关系三元组候选
- Neo4j 子图扩展：
  - `expand_graph_by_entities`：以实体名列表作为起点扩图，并对多起点结果做合并去重
  - `expand_graph_by_triples`：从 (head_name, tail_name) 抽取实体名后再扩图

说明：
- “如何把这些 primitives 组合成 native/local/global/keyword 等策略”应由更高层负责，
  例如 `grag/retrieval/advanced_retrieval_manager.py`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.model.embedding_client import EmbeddingClient
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository

from .keyword_retriever import KeywordRetriever, KeywordChunkHit
from .semantic_retriever import SemanticRetriever, SemanticChunkHit
from .graph_retriever import GraphRetriever, GraphSubgraphResult

GLOBAL_GRAPH_DOC_ID = "__global__"


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
        # Chunk 检索器：
        # - KeywordRetriever：走结构化存储（例如 Postgres）的文本匹配。
        # - SemanticRetriever：走向量库（Milvus）做 ANN，再回填 chunk 文本等信息。
        self._keyword = KeywordRetriever()
        self._semantic = SemanticRetriever(
            embedding_provider=embedding_provider,
            milvus_collection_name=milvus_collection_name,
        )

        # 图检索器（Neo4j）：负责以实体名为入口做子图搜索/扩展。
        self._graph = GraphRetriever()

        # graph_index（entity/relation embeddings）相关依赖：
        # - 该 collection 独立于 chunk embeddings（SemanticRetriever 使用的 collection）。
        # - 该 index 的用途是：
        #   1) 将 query 向量化
        #   2) 在 graph_index 中做 ANN 召回（kind=entity / kind=relation）
        #   3) 将召回结果（实体名、关系端点）作为 Neo4j 扩图起点（由上层策略决定如何用）
        dm = get_data_manager()
        settings = get_config_manager().get_settings()
        self._graph_index_repo = MilvusGraphIndexRepository(
            dm.get_milvus_client(),
            collection_name=str(
                milvus_graph_index_collection_name
                or settings.get_default_graph_index_collection_name()
            ),
        )

        # EmbeddingClient：用于将查询文本编码为向量。
        # 注意：这里是 query embedding，不是文档/实体的离线 embedding（后者在构建阶段完成并写入 Milvus）。
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)

    @staticmethod
    def _merge_subgraphs(subgraphs: list[GraphSubgraphResult]) -> GraphSubgraphResult:
        """将多个子图结果合并为一个子图。

        说明：
        - GraphRetriever.search 返回的 nodes/edges 是 list[dict]。
        - 不同起点扩图可能产生重复节点/边，因此这里做去重合并。
        - 去重 key 尽量使用稳定字段；字段缺失时退化为 repr(dict)（仍可工作但不保证最优）。
        """

        # 为了做到“多起点扩图”的可用合并：
        # - nodes：尽量用稳定字段生成 key（labels/group_id/doc_id/name）
        # - edges：由于当前 edge dict 不包含起止点，使用一组字段生成近似稳定 key
        nodes_by_key: dict[str, dict] = {}
        edges_by_key: dict[str, dict] = {}

        def _node_key(n: dict) -> str:
            # labels 可能是 list/str/None；这里直接用于字符串拼接做 key。
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

    def search_chunks_vector(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[SemanticChunkHit]:
        """向量检索 chunk（SemanticRetriever）。

        说明：
        - 该函数只做“直接召回”，不做 rerank、不做融合。
        - doc_id/doc_time_start/doc_time_end 由底层 retriever 负责解释为过滤条件。
        """
        return self._semantic.search(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
        )

    def search_chunks_keyword(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[KeywordChunkHit]:
        """关键字检索 chunk（KeywordRetriever）。

        说明：
        - 该函数只做“直接召回”，不做 rerank、不做融合。
        """
        return self._keyword.search(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
        )

    def search_entities_vector(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
    ) -> list[dict]:
        """在 graph_index(kind=entity) 中做向量召回。

        返回值：
        - list[dict]：由 MilvusGraphIndexRepository 返回的命中记录。
        - 常用字段：name / doc_id / group_id / source_id / pk / score 等（取决于 output_fields）。

        说明：
        - 该函数只负责“向量召回实体”，不做 Neo4j 扩图。
        - query 为空时直接返回空列表，避免无意义 embedding 与向量检索。
        """
        if not str(query or "").strip():
            return []
        qv = self._embedding_client.embed_query(str(query))
        effective_doc_id = doc_id if doc_id is not None else GLOBAL_GRAPH_DOC_ID
        return self._graph_index_repo.search(
            group_id=group_id,
            kind="entity",
            query_vector=qv,
            top_k=int(top_k),
            doc_id=effective_doc_id,
            output_fields=output_fields,
        )

    def search_relations_vector(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
    ) -> list[dict]:
        """在 graph_index(kind=relation) 中做向量召回。

        返回值：
        - list[dict]：关系候选（通常包含 head_name/tail_name/relation_type 等字段）。

        说明：
        - 该函数只负责“向量召回关系候选”，不做 Neo4j 扩图。
        - query 为空时直接返回空列表，避免无意义 embedding 与向量检索。
        """
        if not str(query or "").strip():
            return []
        qv = self._embedding_client.embed_query(str(query))
        effective_doc_id = doc_id if doc_id is not None else GLOBAL_GRAPH_DOC_ID
        return self._graph_index_repo.search(
            group_id=group_id,
            kind="relation",
            query_vector=qv,
            top_k=int(top_k),
            doc_id=effective_doc_id,
            output_fields=output_fields,
        )

    def expand_graph_by_entities(
        self,
        *,
        group_id: str,
        entity_names: Iterable[str],
        max_depth: int = 2,
        limit: int = 50,
        doc_id: Optional[str] = None,
    ) -> GraphSubgraphResult:
        """以实体名列表为起点做 Neo4j 子图扩展，并合并多个起点的结果。

        关键点：
        - 会先对 entity_names 去重与 strip。
        - 每个实体名都会调用一次 `GraphRetriever.search`。
        - 最终通过 `_merge_subgraphs` 做去重合并，得到一个子图结果。
        """
        subgraphs: list[GraphSubgraphResult] = []
        seen: set[str] = set()
        for nm in entity_names or []:
            s = str(nm or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            subgraphs.append(
                self._graph.search(
                    group_id=group_id,
                    entity_name=s,
                    max_depth=int(max_depth),
                    limit=int(limit),
                    doc_id=doc_id,
                )
            )
        if not subgraphs:
            return GraphSubgraphResult(nodes=[], edges=[])
        return self._merge_subgraphs(subgraphs)

    def search_relations_by_entities(
        self,
        *,
        group_id: str,
        entity_names: Sequence[str],
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        """输入实体列表，返回与实体相关的关系（Neo4j，1-hop）。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        names = [str(x or "").strip() for x in (entity_names or [])]
        names = [n for n in names if n]
        if not names:
            return []
        return self._graph.relations_by_entities(
            group_id=group_id,
            entity_names=names,
            limit=int(limit),
            doc_id=doc_id,
        )

    def search_entities_by_relations(
        self,
        *,
        group_id: str,
        relation_ids: Optional[Sequence[str]] = None,
        relation_triples: Optional[Sequence[dict]] = None,
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        """输入关系列表，返回与关系相关的实体（Neo4j，端点实体集合）。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        rids = [str(x or "").strip() for x in (relation_ids or [])]
        rids = [x for x in rids if x]
        triples = list(relation_triples or [])

        if not rids and not triples:
            return []

        return self._graph.entities_by_relations(
            group_id=group_id,
            relation_ids=rids,
            relation_triples=triples,
            limit=int(limit),
            doc_id=doc_id,
        )

    def expand_graph_by_triples(
        self,
        *,
        group_id: str,
        triples: Sequence[dict],
        max_depth: int = 2,
        limit: int = 50,
        doc_id: Optional[str] = None,
    ) -> GraphSubgraphResult:
        """以三元组集合为输入扩图。

        行为：
        - 从每条 triple dict 中抽取 `head_name` 与 `tail_name`，作为实体名种子。
        - 委托给 `expand_graph_by_entities` 做去重、扩图与合并。
        """
        names: list[str] = []
        for t in triples or []:
            head = str(t.get("head_name") or "").strip()
            tail = str(t.get("tail_name") or "").strip()
            if head:
                names.append(head)
            if tail:
                names.append(tail)
        return self.expand_graph_by_entities(
            group_id=group_id,
            entity_names=names,
            max_depth=int(max_depth),
            limit=int(limit),
            doc_id=doc_id,
        )
