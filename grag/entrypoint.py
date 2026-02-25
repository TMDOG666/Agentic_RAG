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
        res = api.query(...)

    职责边界：
    - 该类不直接操作 Postgres/Milvus/Neo4j 驱动；所有底层交互由 DataClientGraphStorage 与 RetrievalManager 完成。
    - 该类不做 rerank / vector / graph 算法改动，只负责把参数组织好并调用。
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

    def query(
        self,
        *,
        group_id: str,
        query: str,
        mode: str = "native",
        top_k: int = 20,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
        rerank_enabled: Optional[bool] = None,
        rerank_provider: Optional[str] = None,
        graph_entity_name: Optional[str] = None,
        graph_max_depth: int = 2,
        graph_limit: int = 50,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
    ) -> RetrievalResult:
        """查询检索入口（RetrievalManager 的 Facade）。

        Args:
            group_id:
                必填。用于组级别数据隔离。

            query:
                用户查询。

            mode:
                检索模式。

                支持：
                - native：向量检索 chunk（embedding + Milvus）
                - keyword：关键字检索 chunk（Postgres ILIKE 等）
                - local：低层关键词驱动的子图检索（entity 向量召回 -> 扩图）
                - global：高层关键词驱动的子图检索（relation 向量召回 -> 扩图）

            top_k:
                返回条数（各检索模式会以自己的方式使用 top_k）。

            doc_id/doc_time_start/doc_time_end:
                chunk 检索过滤条件（keyword/semantic 生效；graph 通常不依赖 chunk 时间）。

            rerank_enabled/rerank_provider:
                可选的重排序开关与 provider。
                - 若为 None：遵循 RetrievalManager 内部默认/配置
                - 若显式 True/False：强制覆盖

            graph_entity_name/graph_max_depth/graph_limit:
                graph 检索的入口实体与扩展参数。

            milvus_collection_name:
                semantic 检索使用的 Milvus collection（覆盖默认值）。

            milvus_graph_index_collection_name:
                semantic 检索使用的 Milvus graph index collection（覆盖默认值）。

        Returns:
            RetrievalResult：包含 keyword_hits / semantic_hits / graph（三者的组合）。
        """

        get_config_manager().initialize()

        normalized_mode = str(mode or "").strip().lower() or "native"

        collection = milvus_collection_name
        if collection is None:
            collection = self._query_options.milvus_collection_name

        graph_index_collection = milvus_graph_index_collection_name
        if graph_index_collection is None:
            graph_index_collection = getattr(self._query_options, "milvus_graph_index_collection_name", None)

        rm = RetrievalManager(
            milvus_collection_name=collection,
            milvus_graph_index_collection_name=graph_index_collection,
        )
        if normalized_mode == "native":
            return rm.native(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                doc_time_start=doc_time_start,
                doc_time_end=doc_time_end,
                rerank_enabled=bool(rerank_enabled),
                rerank_provider=rerank_provider,
            )

        if normalized_mode == "keyword":
            return rm.keyword(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                doc_time_start=doc_time_start,
                doc_time_end=doc_time_end,
                rerank_enabled=bool(rerank_enabled),
                rerank_provider=rerank_provider,
            )

        if normalized_mode == "local":
            return rm.local(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                graph_entity_name=graph_entity_name,
                graph_max_depth=int(graph_max_depth),
                graph_limit=int(graph_limit),
                rerank_enabled=bool(rerank_enabled),
                rerank_provider=rerank_provider,
            )

        if normalized_mode == "global":
            return rm.global_(
                group_id=group_id,
                query=query,
                top_k=int(top_k),
                doc_id=doc_id,
                graph_entity_name=graph_entity_name,
                graph_max_depth=int(graph_max_depth),
                graph_limit=int(graph_limit),
                rerank_enabled=bool(rerank_enabled),
                rerank_provider=rerank_provider,
            )

        raise ValueError(f"Unsupported mode: {normalized_mode!r}")
