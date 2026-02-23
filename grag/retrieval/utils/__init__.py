"""grag.retrieval.utils

检索层（retrieval layer）的通用工具集合。

放置原则：
- 这里的代码通常是“无状态”或“轻状态”的小组件，便于在不同 retriever/manager 之间复用。
- 不在这里直接做“策略编排”（那属于 manager/entrypoint），只提供可组合的基础能力。

当前包含：
- `Vectorizer`：对 EmbeddingClient 的薄封装，提供统一向量化接口（query/texts）。
- `rerank_chunk_hits` / `rerank_graph_nodes`：可选重排序能力（未配置/失败时稳定降级）。
"""

from .vectorizer import Vectorizer
from .reranker import RerankDebugInfo, rerank_chunk_hits, rerank_graph_nodes

__all__ = [
    "Vectorizer",
    "RerankDebugInfo",
    "rerank_chunk_hits",
    "rerank_graph_nodes",
]
