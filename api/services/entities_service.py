from __future__ import annotations

"""api.services.entities_service

EntitiesService：实体 CRUD 业务层。

存储：
- Postgres `grag_entities`（doc 级实体）。

关于 entity_id：
- 本项目用 uuid5 生成确定性 ID：uuid5(namespace, "{group_id}:{doc_id}:{canonical_name}")
- 这样做的好处：
  - 幂等写入（同一个实体重跑构建得到相同 id）
  - 可跨系统关联（Milvus graph_index / Neo4j 节点属性）
"""

from uuid import UUID, uuid5

from grag.data_client import get_data_manager
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import GraphEntityRecord

from api.schemas.entities import EntityCreateIn, EntityUpdateIn


_GRAG_NAMESPACE = UUID("6b45223b-b3b8-4a2f-b7b7-3d6ad9d2f3f0")


class EntitiesService:
    """实体 CRUD 服务（主要用于管理/调试）。"""

    def __init__(self) -> None:
        """初始化 Postgres repo。"""
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())

    @staticmethod
    def _make_entity_id(*, group_id: str, doc_id: str, canonical_name: str) -> str:
        """按稳定规则生成 entity_id（uuid5）。"""
        return str(uuid5(_GRAG_NAMESPACE, f"{group_id}:{doc_id}:{canonical_name}"))

    def list_entities(self, *, group_id: str, limit: int = 200) -> list[GraphEntityRecord]:
        """列出 group 下实体。"""
        return list(self._pg.list_group_entities(group_id=group_id, limit=int(limit)) or [])

    def get_entity(self, *, group_id: str, entity_id: str) -> GraphEntityRecord | None:
        """按 entity_id 获取实体。"""
        return self._pg.get_entity_by_id(group_id=group_id, entity_id=entity_id)

    def create_entity(self, *, group_id: str, payload: EntityCreateIn) -> GraphEntityRecord:
        """创建实体（底层为 upsert）。"""
        entity_id = payload.entity_id
        if not entity_id:
            # 不传 entity_id 时，按规则生成稳定 id。
            entity_id = self._make_entity_id(group_id=group_id, doc_id=payload.doc_id, canonical_name=payload.canonical_name)

        e = GraphEntityRecord(
            entity_id=str(entity_id),
            group_id=str(group_id),
            doc_id=str(payload.doc_id),
            canonical_name=str(payload.canonical_name),
            type=str(payload.type),
            aliases=list(payload.aliases or []),
            description=str(payload.description or ""),
        )
        self._pg.upsert_entity(entity=e)
        return e

    def update_entity(self, *, group_id: str, entity_id: str, payload: EntityUpdateIn) -> GraphEntityRecord:
        """更新实体（upsert 语义）。"""
        existing = self._pg.get_entity_by_id(group_id=group_id, entity_id=entity_id)
        if existing is None:
            # Upsert semantics: if not exists, create using provided fields.
            canonical_name = payload.canonical_name
            if not canonical_name:
                raise ValueError("canonical_name is required when creating a new entity")
            doc_id = payload.doc_id
            if not doc_id:
                raise ValueError("doc_id is required when creating a new entity")
            e = GraphEntityRecord(
                entity_id=str(entity_id),
                group_id=str(group_id),
                doc_id=str(doc_id),
                canonical_name=str(canonical_name),
                type=str(payload.type or ""),
                aliases=list(payload.aliases or []),
                description=str(payload.description or ""),
            )
            self._pg.upsert_entity(entity=e)
            return e

        e = GraphEntityRecord(
            entity_id=str(existing.entity_id),
            group_id=str(existing.group_id),
            doc_id=str(payload.doc_id or existing.doc_id),
            canonical_name=str(payload.canonical_name or existing.canonical_name),
            type=str(payload.type or existing.type),
            aliases=list(payload.aliases if payload.aliases is not None else existing.aliases),
            description=str(payload.description if payload.description is not None else existing.description),
        )
        self._pg.upsert_entity(entity=e)
        return e

    def delete_entity(self, *, group_id: str, entity_id: str) -> bool:
        """删除实体（仅 Postgres）。"""
        return bool(self._pg.delete_entity(group_id=group_id, entity_id=entity_id))
