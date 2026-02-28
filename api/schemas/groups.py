from __future__ import annotations

"""api.schemas.groups

Group 相关 schema。

说明：
- 当前 MVP 的 group 输出仅包含 group_id。
- group_name/group_desc 属于管理元信息，当前不在查询接口返回（可按需扩展）。
"""

from pydantic import BaseModel


class GroupOut(BaseModel):
    """group 输出结构。"""
    group_id: str
