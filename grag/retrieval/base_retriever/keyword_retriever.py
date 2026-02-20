"""grag.retrieval.keyword_retriever

关键词检索（Keyword Retrieval）：
- 直接在 Postgres 的 chunk 文本字段上做 ILIKE 匹配
- 支持 group_id 强制过滤
- 支持 doc_id 过滤
- 支持 doc_time_start/doc_time_end 过滤（通过 JOIN documents 表实现）

定位：
- 这是最简单、最“可解释”的召回方式；
- 召回质量依赖原文是否包含关键词；
- 是否重排序（rerank）由 RetrievalManager 决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from grag.data_client import get_data_manager
from grag.storage.repositories.postgres_repository import PostgresGraphRepository


@dataclass(frozen=True)
class KeywordChunkHit:
    """关键词检索命中结果."""
    group_id: str
    doc_id: str
    chunk_id: str
    index: int
    text: str


class KeywordRetriever:
    """关键词检索器."""
    def __init__(self) -> None:
        # Keyword 检索完全走 Postgres，不需要 embedding/vector DB。
        dm = get_data_manager()
        self._pg_repo = PostgresGraphRepository(dm.get_postgres_client())

    def search(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 20,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[KeywordChunkHit]:
        """执行关键词检索.

        Args:
            group_id: 必填，数据隔离维度.
            query: 查询文本（会作为 ILIKE 条件）.
            top_k: 返回条数.
            doc_id: 可选，只在指定 doc 内检索.
            doc_time_start/doc_time_end: 可选，按文档时间范围过滤.

        Returns:
            命中的 chunk 列表（包含 chunk_id、doc_id、chunk index 以及文本）.
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(query or "").strip():
            return []

        # Postgres 侧完成关键词匹配与过滤条件.
        chunks = self._pg_repo.search_chunks_by_keyword(
            group_id=group_id,
            query=query,
            limit=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
        )

        return [
            KeywordChunkHit(
                group_id=c.group_id,
                doc_id=c.doc_id,
                chunk_id=c.chunk_id,
                index=int(c.index),
                text=c.text,
            )
            for c in chunks
        ]