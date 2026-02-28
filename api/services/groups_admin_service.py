from __future__ import annotations

"""api.services.groups_admin_service

GroupsAdminService：group 管理（创建/删除）服务。

删除语义（doc 级）：
- 先从 Postgres 列出该 group 下所有 doc_id
- 然后分别清理：
  - Milvus chunk embeddings（按 doc_id expr 删除）
  - Milvus graph_index embeddings（按 group_id expr 删除）
  - Neo4j 图（按 group_id 删除 Document/Entity 节点及其关系）
  - Postgres 结构化资产（对每个 doc 做 delete_document_assets）

注意：
- 这里是 best-effort 清理外部存储；任何外部失败不会阻止 Postgres 最终删除。
"""

from datetime import datetime, timezone

from grag.data_client import get_data_manager
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository
from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository

from api.schemas.groups_admin import GroupCreateIn


class GroupsAdminService:
    """group 管理服务。"""

    def __init__(self) -> None:
        """初始化所需仓储。"""
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())
        self._neo4j = Neo4jGraphRepository(dm.get_neo4j_client())
        self._milvus = MilvusVectorRepository(dm.get_milvus_client())
        self._graph_index = MilvusGraphIndexRepository(
            dm.get_milvus_client(),
            collection_name=str("grag_graph_index"),
        )

    def create_group(self, payload: GroupCreateIn) -> None:
        """创建/更新 group 元信息。"""
        created_at = datetime.now(timezone.utc).isoformat()
        self._pg.create_group(
            group_id=payload.group_id,
            group_name=payload.group_name or "",
            group_desc=payload.group_desc or "",
            created_at=created_at,
        )

    def delete_group(self, *, group_id: str) -> None:
        """删除 group 及其所有文档资产（doc 级级联删除）。"""
        doc_ids = self._pg.list_group_doc_ids(group_id=group_id)

        # Milvus chunk embeddings: delete per doc best-effort
        for doc_id in doc_ids:
            try:
                self._milvus.delete_by_doc_id(group_id=group_id, doc_id=doc_id)
            except Exception:
                pass

        # Milvus graph index embeddings
        try:
            self._graph_index.delete_by_group_id(group_id=group_id)
        except Exception:
            pass

        # Neo4j graph
        try:
            self._neo4j.delete_group_graph(group_id=group_id)
        except Exception:
            pass

        # Postgres rows
        for doc_id in doc_ids:
            self._pg.delete_document_assets(group_id=group_id, doc_id=doc_id)
