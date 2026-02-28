from __future__ import annotations

"""api.services.documents_service

DocumentsService：文档查询与删除的业务层封装。

重点：doc 级级联删除
- 文档在构建流程中会派生出多种资产，分布在不同存储：
  - Postgres: documents/chunks/entities/relations
  - Milvus: chunk embeddings
  - Milvus graph_index: entity/relation embeddings
  - Neo4j: 图节点与关系
- 删除时必须尽可能把这些资产一起清理，否则会出现：
  - 检索命中已删除文档的向量
  - 图查询出现悬挂节点/边
"""

from grag.data_client import get_data_manager
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository
from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import DocumentRecord


class DocumentsService:
    """文档查询与删除服务（doc 级）。"""

    def __init__(self) -> None:
        """初始化各存储仓储。"""
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())
        self._neo4j = Neo4jGraphRepository(dm.get_neo4j_client())
        self._milvus = MilvusVectorRepository(dm.get_milvus_client())
        self._graph_index = MilvusGraphIndexRepository(
            dm.get_milvus_client(),
            collection_name=str("grag_graph_index"),
        )

    def list_documents(self, *, group_id: str, limit: int = 200) -> list[DocumentRecord]:
        """列出 group 下文档。"""
        return list(self._pg.list_group_documents(group_id=group_id, limit=int(limit)) or [])

    def get_document(self, *, group_id: str, doc_id: str) -> DocumentRecord | None:
        """读取单个文档元信息。"""
        return self._pg.get_document(group_id=group_id, doc_id=doc_id)

    def delete_document(self, *, group_id: str, doc_id: str) -> None:
        """删除文档及其派生资产（best-effort 清理外部存储）。

        删除顺序的考虑：
        - 先删向量/图（外部系统），再删 Postgres（权威结构化存储）。
        - 即使外部清理失败，最后也会删除 Postgres 记录，让“权威来源”先一致。
        """

        # 1) chunk embeddings (Milvus)
        # 先从 Postgres 查 chunk_id（Milvus 的 pk = {group_id}:{chunk_id}）
        chunk_ids = self._pg.list_doc_chunk_ids(group_id=group_id, doc_id=doc_id)
        try:
            self._milvus.delete_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        except Exception:
            # best-effort cleanup
            pass

        # 2) graph_index embeddings（entity/relation embeddings）
        try:
            self._graph_index.delete_by_doc_id(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass

        # 3) Neo4j graph（doc 级节点与关系）
        try:
            self._neo4j.delete_document_graph(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass

        # 4) Postgres rows：最后清理结构化权威存储
        self._pg.delete_document_assets(group_id=group_id, doc_id=doc_id)
