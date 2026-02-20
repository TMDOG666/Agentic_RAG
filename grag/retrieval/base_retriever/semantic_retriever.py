"""grag.retrieval.semantic_retriever

语义检索（Semantic Retrieval）：
- 使用 EmbeddingClient 将 query 向量化
- 在 Milvus 中执行向量近邻检索（召回 chunk_id）
- 回源 Postgres 批量取回 chunk 文本

本模块定位：
- 只做“召回”，不做跨模型融合。
- 是否重排序（rerank）由 RetrievalManager 决定。

重要约束：
- group_id 必填：用于数据隔离，避免跨组召回。
- doc_time_start/doc_time_end 为可选过滤条件：
  - 过滤逻辑在 Milvus 侧完成（基于 collection 中的 doc_time 字段）。
  - doc_time 建议为 ISO8601 字符串（否则字符串比较可能不符合时间排序语义）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from grag.data_client import get_data_manager
from grag.model.embedding_client import EmbeddingClient
from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository


@dataclass(frozen=True)
class SemanticChunkHit:
    """语义检索命中结果."""
    group_id: str
    doc_id: str
    doc_time: str
    chunk_id: str
    score: float
    text: str


class SemanticRetriever:
    """语义检索器."""

    def __init__(
        self,
        *,
        embedding_provider: Optional[str] = None,
        milvus_collection_name: Optional[str] = None,
    ) -> None:
        # DataManager 是项目内统一的数据/连接管理入口：
        # - PostgresClient
        # - MilvusClient
        # - Neo4jClient
        dm = get_data_manager()

        # embedding_provider 为可选覆盖：
        # - None: 使用配置默认 embedding provider
        # - str : 强制使用指定 provider
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)

        # milvus_collection_name 为可选覆盖：用于测试/多租户隔离。
        self._milvus_repo = MilvusVectorRepository(
            dm.get_milvus_client(),
            collection_name=milvus_collection_name,
        )
        self._pg_repo = PostgresGraphRepository(dm.get_postgres_client())

    def search(
        self,
        *,
        group_id: str,
        query: str,
        top_k: int = 10,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[SemanticChunkHit]:
        """执行语义检索。

        Args:
            group_id: 必填，数据隔离维度。
            query: 查询文本。
            top_k: 召回数量。
            doc_id: 可选，只在指定 doc 内检索。
            doc_time_start/doc_time_end: 可选，按文档时间范围过滤（Milvus 侧过滤）。

        Returns:
            命中的 chunk 列表（包含 chunk_id、doc_id、doc_time、文本以及 Milvus 返回的相似度/距离分数）。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(query or "").strip():
            return []

        # 1) query -> vector
        qv = self._embedding_client.embed_query(query)

        # 2) Milvus 向量检索：返回的 rows 中应包含 chunk_id / doc_id / doc_time 以及 score
        rows = self._milvus_repo.search_chunk_embeddings(
            group_id=group_id,
            query_vector=qv,
            top_k=int(top_k),
            doc_id=doc_id,
            doc_time_start=doc_time_start,
            doc_time_end=doc_time_end,
            output_fields=["group_id", "doc_id", "doc_time", "chunk_id"],
        )

        # 3) 回源 Postgres：Milvus 中只存了 chunk 元信息，不存 chunk 全文
        chunk_ids: list[str] = [str(r.get("chunk_id")) for r in rows if r.get("chunk_id")]
        chunks = self._pg_repo.get_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        chunk_text_by_id = {c.chunk_id: c.text for c in chunks}

        hits: list[SemanticChunkHit] = []
        for r in rows:
            cid = str(r.get("chunk_id") or "")
            if not cid:
                continue

            # 注意：Postgres 回源可能拿不到某些 chunk（例如数据不一致/已被清理）。
            # 此时 text 为空字符串，仍返回该条以便上层可观测问题。
            hits.append(
                SemanticChunkHit(
                    group_id=str(r.get("group_id") or group_id),
                    doc_id=str(r.get("doc_id") or ""),
                    doc_time=str(r.get("doc_time") or ""),
                    chunk_id=cid,
                    score=float(r.get("score") or 0.0),
                    text=str(chunk_text_by_id.get(cid, "")),
                )
            )
        return hits