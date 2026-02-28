from __future__ import annotations

"""api.schemas.groups_admin

Group 管理接口 schema。

说明：
- 当前仅支持创建 group 元信息（group_id/name/desc）。
- 删除 group 走 path 参数，不需要 schema。
"""

from typing import Optional

from pydantic import BaseModel


class GroupCreateIn(BaseModel):
    """创建/更新 group 元信息入参。"""
    group_id: str
    group_name: Optional[str] = None
    group_desc: Optional[str] = None
