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

from typing import Optional, Sequence

from grag.retrieval.base_retriever.base_retrieval_manager import (
    BaseRetrievalManager,
    RetrievalResult,
)


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
    def _normalize_modes(modes: Sequence[str]) -> list[str]:
        out: list[str] = []
        for m in modes or []:
            s = str(m).strip().lower()
            if not s:
                continue
            out.append(s)
        return out

    def search(
        self,
        *,
        group_id: str,
        query: str,
        modes: Sequence[str],
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
        """高级检索入口。

        说明：
        - `modes` 可以直接传基础模式（keyword/semantic/vector/graph/local/global）。
        - 也可以传高级别名：
          - native -> semantic
          - local/global -> 组合 keyword + vector + local/global

        注意：
        - local/global 的“高/低层拆分”由 BaseRetrievalManager 内部的 split_high_low 负责。
        """

        normalized = self._normalize_modes(modes)

        expanded: list[str] = []
        for m in normalized:
            if m == "native":
                expanded.append("vector")
            elif m == "local":
                expanded.extend(["keyword", "vector", "local"])
            elif m == "global":
                expanded.extend(["keyword", "vector", "global"])
            else:
                expanded.append(m)

        seen: set[str] = set()
        unique_expanded: list[str] = []
        for m in expanded:
            if m in seen:
                continue
            seen.add(m)
            unique_expanded.append(m)

        return self._base.search(
            group_id=group_id,
            query=query,
            modes=unique_expanded,  # type: ignore[arg-type]
            top_k=int(top_k),
            rerank_enabled=bool(rerank_enabled),
            rerank_provider=rerank_provider,
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
            graph_entity_name=graph_entity_name,
            graph_max_depth=int(graph_max_depth),
            graph_limit=int(graph_limit),
        )
