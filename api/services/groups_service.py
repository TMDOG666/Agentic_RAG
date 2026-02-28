from __future__ import annotations

"""api.services.groups_service

GroupsService：group 查询相关的业务层封装。

职责：
- 从 Postgres（结构化存储）读取 group 列表、文档元信息。
- 从 Neo4j（图存储）读取 group 图谱（nodes/edges）。

边界：
- 本 service 不负责写入/删除；写入在 ingest，删除在 documents/groups_admin。
"""

from typing import Optional

from grag.data_client import get_data_manager
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import DocumentRecord


class GroupsService:
    """Group 只读查询服务。"""

    def __init__(self) -> None:
        """初始化依赖。

        说明：
        - DataManager 是项目统一的数据连接入口（Postgres/Milvus/Neo4j 等）。
        - 这里采用“每个 service 自己拿 repo”的轻量方式，方便 API 层解耦。
        """
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())
        self._neo4j = Neo4jGraphRepository(dm.get_neo4j_client())

    def list_groups(self, *, limit: int = 500) -> list[str]:
        """列出 group_id 列表。"""
        return self._pg.list_groups(limit=int(limit))

    def list_group_documents(
        self,
        *,
        group_id: str,
        limit: int = 200,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[DocumentRecord]:
        """列出 group 下的文档元信息。"""
        return list(
            self._pg.list_group_documents(
                group_id=group_id,
                limit=int(limit),
                doc_time_start=doc_time_start,
                doc_time_end=doc_time_end,
            )
        )

    def get_group_graph(self, *, group_id: str, limit: int = 200, doc_id: Optional[str] = None) -> dict:
        """从 Neo4j 读取 group 图谱。

        Returns:
            dict: {"nodes": [...], "edges": [...]}。
        """
        return self._neo4j.search_group_graph(group_id=group_id, limit=int(limit), doc_id=doc_id)
