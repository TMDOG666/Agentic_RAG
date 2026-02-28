from __future__ import annotations

"""api.controllers.skills_controller

Skills 管理相关接口。

Skills 是本项目 Agent 技能体系的一部分：
- Skills 目录通常位于 `.cursor/skills/<skill_name>/SKILL.md`
- SkillManager 负责扫描与缓存元数据、按需加载指令、读取引用文件、执行技能脚本

这些接口的主要用途：
- 前端查看当前可用 skills
- 调试/人工触发：加载技能指令、读取技能文件、执行技能脚本
"""

from fastapi import APIRouter

from api.schemas.skills import SkillExecuteIn, SkillFileReadIn, SkillLoadIn, SkillOut
from api.services.skills_service import SkillsService

router = APIRouter()


@router.get("")
def list_skills() -> list[SkillOut]:
    """列出可用 skills（仅元信息）。"""
    svc = SkillsService()
    return svc.list_skills()


@router.post("/load")
def load_skill(payload: SkillLoadIn) -> dict:
    """加载某个 skill 的正文指令（剥离 front matter 后的内容）。"""
    svc = SkillsService()
    return {"content": svc.load_skill(payload.skill_name)}


@router.post("/read-file")
def read_skill_file(payload: SkillFileReadIn) -> dict:
    """读取某个 skill 目录下的额外文件（通常由 SKILL.md 中 [[filename]] 引用触发）。"""
    svc = SkillsService()
    return {"content": svc.read_skill_file(payload.skill_name, payload.filename)}


@router.post("/execute")
def execute_skill_script(payload: SkillExecuteIn) -> dict:
    """执行某个 skill 目录内的脚本，并返回 stdout/stderr。

    注意：
    - 该接口会执行本机脚本，属于高权限能力。
    - 当前 MVP 未做鉴权；如果部署到共享环境，强烈建议加鉴权/隔离。
    """
    svc = SkillsService()
    return {"content": svc.execute_skill_script(payload.skill_name, payload.script_name, payload.args or "")}
