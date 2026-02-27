from __future__ import annotations

"""grag.entrypoint

对外“总入口”（Facade）。

为什么需要这个模块：
- grag 内部模块较多（config / storage / graph_construction / retrieval），对外直接使用时需要了解较多细节；
- 在 Agent/Service/CLI 等场景里，经常只需要两个能力：
  1) 把一段文本/文档构建成知识图谱并落库
  2) 基于已落库的数据进行检索（keyword / semantic / graph）

该 Facade 的设计原则：
- 只做“调用编排”和“默认值收敛”，不改变底层算法逻辑；
- 自动初始化配置（通过 get_config_manager().initialize()），避免上层忘记初始化导致 RuntimeError；
- 尽量暴露必要参数（group_id、collection、top_k、过滤条件等），其余保持内部默认。
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from grag.config import get_config_manager
from grag.graph_construction.graph_builder import GraphBuildResult, GraphBuilder
from grag.retrieval import RetrievalManager, RetrievalResult
from grag.storage.storage_impl import DataClientGraphStorage


@dataclass(frozen=True)
class BuildOptions:
    """构建（build_kg）侧的默认选项。

    说明：
    - build_kg 会创建 DataClientGraphStorage，从而决定 Milvus collection 与写入策略。
    - 这些值可以：
      - 在创建 GRAG(api) 时作为默认值传入
      - 或在每次 build_kg 调用时通过参数覆盖
    """

    milvus_collection_name: Optional[str] = None
    milvus_upsert_strategy: str = "delete_then_insert"
    milvus_graph_index_collection_name: Optional[str] = None


@dataclass(frozen=True)
class QueryOptions:
    """查询（query）侧的默认选项。

    注意：
    - semantic 检索会依赖 Milvus collection。
    - keyword/graph 不依赖 Milvus，但仍可复用同一个 collection 配置以保持一致。
    """

    milvus_collection_name: Optional[str] = None
    milvus_graph_index_collection_name: Optional[str] = None


class GRAG:
    """对外 Facade：封装“构建知识图谱”和“查询检索”两条主链路。

    典型用法：
        from grag import GRAG

        api = GRAG()
        api.build_kg(...)
        res = api.chunks_vector(...)

    职责边界：
    - 该类不直接操作 Postgres/Milvus/Neo4j 驱动；所有底层交互由 DataClientGraphStorage 与 RetrievalManager 完成。
    - 该类不做 rerank / vector / graph 算法改动，只负责把参数组织好并调用。

    设计目标：
    - 对外提供“原子、可组合”的检索范式入口，便于上层/agent 灵活编排。
    """

    def __init__(
        self,
        *,
        build_options: Optional[BuildOptions] = None,
        query_options: Optional[QueryOptions] = None,
    ) -> None:
        """创建 Facade。

        Args:
            build_options: build_kg 的默认配置（例如默认 Milvus collection）。
            query_options: query 的默认配置（例如默认 Milvus collection）。

        默认策略：
        - 若未显式传 query_options，则默认沿用 build_options.milvus_collection_name。
          这样“构建写入”和“查询检索”会自然落到同一个 collection。
        """

        self._build_options = build_options or BuildOptions()
        self._query_options = query_options or QueryOptions(
            milvus_collection_name=self._build_options.milvus_collection_name,
            milvus_graph_index_collection_name=self._build_options.milvus_graph_index_collection_name,
        )

    def build_kg(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str,
        doc_id: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_upsert_strategy: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> GraphBuildResult:
        """构建知识图谱并落库（GraphBuilder.build_and_save 的 Facade）。

        你传入：
        - text: 文本内容（通常是 docx/pdf 解析后的纯文本）
        - doc_time: 文档时间（建议 ISO8601）
        - doc_name: 文档名（用于展示/追踪）
        - group_id: 数据隔离维度（强烈建议外部调用方显式指定）

        可选：
        - doc_id: 若不传，内部会生成并写入（同时影响 chunk_id 前缀）
        - milvus_collection_name: 本次写入使用的 Milvus collection（覆盖默认值）
        - milvus_upsert_strategy: Milvus 写入策略（覆盖默认值）
        - milvus_graph_index_collection_name: 本次写入使用的 Milvus graph index collection（覆盖默认值）

        Returns:
            GraphBuildResult：包含 construction 流程结果 + 入库的 document/chunks/embeddings/entities/relations。

        默认值来源（覆盖顺序从高到低）：
        - 本次 build_kg 传入的 milvus_* 参数
        - 创建 GRAG 时传入的 build_options

        重要约定：
        - group_id 是外部隔离维度：所有写入都会带上 group_id，用于后续检索过滤。
        """

        get_config_manager().initialize()

        collection = milvus_collection_name
        if collection is None:
            collection = self._build_options.milvus_collection_name

        upsert = milvus_upsert_strategy
        if upsert is None:
            upsert = self._build_options.milvus_upsert_strategy

        graph_index_collection = milvus_graph_index_collection_name
        if graph_index_collection is None:
            graph_index_collection = getattr(self._build_options, "milvus_graph_index_collection_name", None)

        storage = DataClientGraphStorage(
            milvus_collection_name=collection,
            milvus_graph_index_collection_name=graph_index_collection,
            milvus_upsert_strategy=upsert,
        )
        builder = GraphBuilder(storage=storage)
        return builder.build_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
        )

    def _make_retrieval_manager(
        self,
        *,
        milvus_collection_name: Optional[str],
        milvus_graph_index_collection_name: Optional[str],
    ) -> RetrievalManager:
        """创建 RetrievalManager，并在此处统一做：

        - config 初始化（get_config_manager().initialize()）
        - milvus collection 与 graph index collection 的默认值归并

        默认值来源（覆盖顺序从高到低）：
        - 本次调用 chunks_vector/chunks_keyword/entities/relations 传入的 milvus_* 参数
        - 创建 GRAG 时传入的 query_options
        - 若未传 query_options，则默认沿用 build_options（见 __init__）
        """
        get_config_manager().initialize()

        collection = milvus_collection_name
        if collection is None:
            collection = self._query_options.milvus_collection_name

        graph_index_collection = milvus_graph_index_collection_name
        if graph_index_collection is None:
            graph_index_collection = getattr(self._query_options, "milvus_graph_index_collection_name", None)

        return RetrievalManager(
            milvus_collection_name=collection,
            milvus_graph_index_collection_name=graph_index_collection,
        )

    def chunks_vector(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 20,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
        rerank_enabled: Optional[bool] = None,
        rerank_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> RetrievalResult:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.chunks_vector(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
            rerank_enabled=bool(rerank_enabled),
            rerank_provider=rerank_provider,
        )

    def chunks_keyword(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 20,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
        rerank_enabled: Optional[bool] = None,
        rerank_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> RetrievalResult:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.chunks_keyword(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
            rerank_enabled=bool(rerank_enabled),
            rerank_provider=rerank_provider,
        )

    def entities(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 20,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> list[dict]:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.entities(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            output_fields=list(output_fields) if output_fields is not None else None,
        )

    def relations(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 20,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> list[dict]:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.relations(
            group_id=group_id,
            query=query,
            top_k=int(top_k),
            doc_id=doc_id,
            output_fields=list(output_fields) if output_fields is not None else None,
        )

    def relations_by_entities(
        self,
        *,
        group_id: str,
        entity_names: Sequence[str],
        limit: int = 200,
        doc_id: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> list[dict]:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.relations_by_entities(
            group_id=group_id,
            entity_names=list(entity_names or []),
            limit=int(limit),
            doc_id=doc_id,
        )

    def entities_by_relations(
        self,
        *,
        group_id: str,
        relation_ids: Optional[Sequence[str]] = None,
        relation_triples: Optional[Sequence[dict]] = None,
        limit: int = 200,
        doc_id: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> list[dict]:
        rm = self._make_retrieval_manager(
            milvus_collection_name=milvus_collection_name,
            milvus_graph_index_collection_name=milvus_graph_index_collection_name,
        )
        return rm.entities_by_relations(
            group_id=group_id,
            relation_ids=list(relation_ids or []) if relation_ids is not None else None,
            relation_triples=list(relation_triples or []) if relation_triples is not None else None,
            limit=int(limit),
            doc_id=doc_id,
        )
