from __future__ import annotations

"""api.schemas.skills

Skills 相关 schema。

说明：
- skills 接口大多返回纯文本内容，因此 controller 返回 `{"content": ...}`。
- 这里的 schema 主要用于：
  - list_skills 的结构化输出（name/description）
  - load/read/execute 的入参校验
"""

from typing import Optional

from pydantic import BaseModel


class SkillOut(BaseModel):
    """skill 列表输出项。"""
    name: str
    description: str


class SkillLoadIn(BaseModel):
    """加载 skill 指令入参。"""
    skill_name: str


class SkillFileReadIn(BaseModel):
    """读取 skill 文件入参。"""
    skill_name: str
    filename: str


class SkillExecuteIn(BaseModel):
    """执行 skill 脚本入参。"""
    skill_name: str
    script_name: str
    args: Optional[str] = None
