from __future__ import annotations

"""api.controllers.groups_admin_controller

Group 管理类接口。

和 `groups_controller` 的区别：
- `groups_controller`：只读查询
- `groups_admin_controller`：创建/删除（会产生副作用，尤其是删除会级联清理数据）

注意：
- 当前 MVP 未做鉴权；如果部署到共享环境，建议对这些管理接口加鉴权。
"""

from fastapi import APIRouter

from api.schemas.groups_admin import GroupCreateIn
from api.services.groups_admin_service import GroupsAdminService

router = APIRouter()


@router.post("")
def create_group(payload: GroupCreateIn) -> dict:
    """创建（或更新）group 元信息。

    说明：
    - 该接口只写入 Postgres 的 `grag_groups` 元信息表。
    - 实际数据是否存在仍以 documents/chunks 等资产为准。
    """
    svc = GroupsAdminService()
    svc.create_group(payload)
    return {"created": True, "group_id": payload.group_id}


@router.delete("/{group_id}")
def delete_group(group_id: str) -> dict:
    """删除 group 及其所有 doc 资产（doc 级循环级联删除）。"""
    svc = GroupsAdminService()
    svc.delete_group(group_id=group_id)
    return {"deleted": True, "group_id": group_id}
