from __future__ import annotations

from typing import Optional, Sequence

from grag.data_client import DataManager, get_data_manager

from .protocol import GraphStorage
from .repositories import MilvusVectorRepository, Neo4jGraphRepository, PostgresGraphRepository
from .types import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphRelationRecord,
)


"""grag.storage.storage_impl

Storage 层的具体实现（Implementation）。

本模块提供 `DataClientGraphStorage`：
- 通过 `grag.data_client.DataManager` 获取三类数据库 client
- 组合三个 repository：
  - PostgresGraphRepository：文档/Chunk 文本/实体元信息
  - MilvusVectorRepository：Chunk embedding
  - Neo4jGraphRepository：图结构（实体节点 + 关系边）

这样上层（GraphBuilder）只依赖 `GraphStorage` 接口，不直接依赖任何数据库 client。
"""


class DataClientGraphStorage(GraphStorage):
    """基于 DataManager 的 GraphStorage 实现。

    单一职责：
    - 将 GraphBuilder 传入的 records 分发给三个 repository 完成落库。

    失败语义：
    - 当前实现为“尽快失败”（fail-fast）：任何一个 repository 抛异常将向上抛出。
    - 注意：这里没有跨库分布式事务；因此出现部分库写入成功、部分失败的情况是可能的。
      如果需要强一致性，应在上层引入幂等重试/补偿机制，或将写入收敛到同一事务系统。
    """

    def __init__(
        self,
        *,
        data_manager: Optional[DataManager] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_upsert_strategy: str = "insert_only",
    ) -> None:
        self._data_manager = data_manager or get_data_manager()
        self._pg_repo = PostgresGraphRepository(self._data_manager.get_postgres_client())
        self._milvus_repo = MilvusVectorRepository(
            self._data_manager.get_milvus_client(),
            collection_name=milvus_collection_name,
            upsert_strategy=milvus_upsert_strategy,
        )
        self._neo4j_repo = Neo4jGraphRepository(self._data_manager.get_neo4j_client())

    def save_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> None:
        """落库单篇文档对应的全部资产。

        输入来自 GraphBuilder（已经完成：chunk_id 对齐、entity/relation canonical 化、embedding 计算）。

        写入顺序（最小可用）：
        1) Postgres：document / chunks / entities
        2) Milvus：chunk embeddings
        3) Neo4j：document / entities / relations

        说明：
        - Postgres 与 Neo4j 都会写 Document/Entity，但目的不同：
          - Postgres：便于检索/回溯/审计（结构化元信息）
          - Neo4j：便于图查询与图推理
        """
        self._pg_repo.upsert_document_and_chunks(
            document=document,
            chunks=chunks,
            entities=entities,
        )
        self._milvus_repo.upsert_chunk_embeddings(
            document=document,
            embeddings=embeddings,
        )
        self._neo4j_repo.upsert_graph(
            document=document,
            entities=entities,
            relations=relations,
        )

    def list_group_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GraphEntityRecord]:
        # 说明：跨文档融合所需的“历史实体候选”目前以 Postgres 为权威来源。
        # - Postgres 存的是结构化实体元信息（canonical/type/aliases/description），读取成本低。
        # - Neo4j 也有实体节点，但当前 key 含 doc_id，且查询/排序策略更复杂；因此此处先走 Postgres。
        return self._pg_repo.list_group_entities(group_id=group_id, limit=limit)
