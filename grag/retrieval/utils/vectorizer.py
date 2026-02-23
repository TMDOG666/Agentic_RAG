from __future__ import annotations

"""grag.retrieval.utils.vectorizer

检索层向量化工具（Vectorizer）。

目的：
- 对 `grag.model.embedding_client.EmbeddingClient` 做一层非常薄的封装，
  让 retrieval 层在需要“把文本变成向量”的地方可以统一调用。

设计约束：
- 该工具不缓存向量结果（避免引入跨请求状态）；如需缓存应由上层显式实现。
- provider 的选择逻辑遵循 EmbeddingClient：
  - `provider_name=None`：使用 settings 默认 embedding provider
  - `provider_name=str`：强制使用指定 provider
"""

from typing import List, Optional

from grag.model.embedding_client import EmbeddingClient


class Vectorizer:
    """EmbeddingClient 的小封装。

    说明：
    - 保持接口最小化：query/texts 两种调用。
    - 对外不暴露底层 embeddings 对象，避免上层误用。
    """

    def __init__(self, *, provider_name: Optional[str] = None) -> None:
        """创建 Vectorizer。

        Args:
            provider_name: 可选，覆盖默认 embedding provider。
        """
        self._client = EmbeddingClient(provider_name=provider_name)

    def embed_query(self, text: str) -> List[float]:
        """把单条查询文本向量化。

        Args:
            text: 查询文本。

        Returns:
            向量（float list）。
        """
        return self._client.embed_query(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """把多条文本批量向量化。

        Args:
            texts: 文本列表。

        Returns:
            向量列表（二维数组）。
        """
        return self._client.embed_texts(texts)
