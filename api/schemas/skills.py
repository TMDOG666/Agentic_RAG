from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SkillOut(BaseModel):
    name: str
    display_name: str
    version: str
    description: str
    type: str
    source: str
    capabilities: list[str] = []


class SkillLoadIn(BaseModel):
    skill_name: str


class SkillFileReadIn(BaseModel):
    skill_name: str
    filename: str


class SkillExecuteIn(BaseModel):
    skill_name: str
    script_name: str
    args: Optional[str] = None
