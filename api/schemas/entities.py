from __future__ import annotations

"""api.schemas.entities

实体（Entity）相关 schema。

注意：
- 本项目的实体是 doc 级 canonical entity（融合后的标准实体名）。
- `entity_id` 为稳定 id（uuid5），用于跨系统关联。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from grag.storage.types import GraphEntityRecord


class EntityBase(BaseModel):
    """实体基础字段。"""

    doc_id: str
    canonical_name: str
    type: str = Field(default="")
    aliases: list[str] = Field(default_factory=list)
    description: str = Field(default="")


class EntityCreateIn(EntityBase):
    """创建实体入参。

    说明：
    - entity_id 可选；不传则由服务端按规则生成。
    """
    entity_id: Optional[str] = None


class EntityUpdateIn(BaseModel):
    """更新实体入参（字段均可选）。

    说明：
    - PUT /entities/{entity_id} 的 entity_id 在 path 中。
    - payload 中的字段为可选覆盖字段。
    """
    doc_id: Optional[str] = None
    canonical_name: Optional[str] = None
    type: Optional[str] = None
    aliases: Optional[list[str]] = None
    description: Optional[str] = None


class EntityOut(EntityBase):
    """实体输出结构。"""

    entity_id: str
    group_id: str

    @staticmethod
    def from_record(e: GraphEntityRecord) -> "EntityOut":
        """从 GraphEntityRecord 转换为 API schema。"""
        return EntityOut(
            entity_id=str(e.entity_id),
            group_id=str(e.group_id),
            doc_id=str(e.doc_id),
            canonical_name=str(e.canonical_name),
            type=str(e.type),
            aliases=list(e.aliases or []),
            description=str(e.description or ""),
        )
