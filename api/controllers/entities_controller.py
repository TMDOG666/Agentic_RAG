from __future__ import annotations

"""api.controllers.entities_controller

实体（Entity）CRUD 接口。

数据来源：
- Postgres `grag_entities` 表（doc 级 canonical entities）。

注意：
- 这里的实体 CRUD 只影响 Postgres 层。
- Neo4j/Milvus 的实体向量/节点来自构建流程（build_kg）；如果你手动修改实体，可能造成跨存储不一致。
- 当前作为 MVP/管理调试接口使用。
"""

from fastapi import APIRouter

from api.schemas.entities import EntityCreateIn, EntityOut, EntityUpdateIn
from api.services.entities_service import EntitiesService

router = APIRouter()


@router.get("")
def list_entities(group_id: str, limit: int = 200) -> list[EntityOut]:
    """列出某个 group 下的实体列表（跨 doc）。"""
    svc = EntitiesService()
    items = svc.list_entities(group_id=group_id, limit=limit)
    return [EntityOut.from_record(x) for x in items]


@router.get("/{entity_id}")
def get_entity(group_id: str, entity_id: str) -> EntityOut | None:
    """按 entity_id 获取实体。"""
    svc = EntitiesService()
    e = svc.get_entity(group_id=group_id, entity_id=entity_id)
    return EntityOut.from_record(e) if e is not None else None


@router.post("")
def create_entity(group_id: str, payload: EntityCreateIn) -> EntityOut:
    """创建实体（底层为 upsert）。"""
    svc = EntitiesService()
    e = svc.create_entity(group_id=group_id, payload=payload)
    return EntityOut.from_record(e)


@router.put("/{entity_id}")
def update_entity(group_id: str, entity_id: str, payload: EntityUpdateIn) -> EntityOut:
    """更新实体。

    说明：
    - 当前实现为 upsert 语义：若 entity_id 不存在，会尝试按 payload 创建。
    """
    svc = EntitiesService()
    e = svc.update_entity(group_id=group_id, entity_id=entity_id, payload=payload)
    return EntityOut.from_record(e)


@router.delete("/{entity_id}")
def delete_entity(group_id: str, entity_id: str) -> dict:
    """删除实体（仅 Postgres）。"""
    svc = EntitiesService()
    ok = svc.delete_entity(group_id=group_id, entity_id=entity_id)
    return {"deleted": bool(ok)}
