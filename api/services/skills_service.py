from __future__ import annotations

from agent.skill.manager import SkillManager

from api.schemas.skills import SkillOut


class SkillsService:
    def __init__(self) -> None:
        self._mgr = SkillManager()

    def list_skills(self) -> list[SkillOut]:
        out: list[SkillOut] = []
        for name, info in (self._mgr.skills_metadata or {}).items():
            out.append(
                SkillOut(
                    name=str(name),
                    display_name=str(info.get("display_name") or name),
                    version=str(info.get("version") or "0.1.0"),
                    description=str(info.get("description") or ""),
                    type=str(info.get("type") or "hybrid-skill"),
                    source=str(info.get("source") or "manifest"),
                    capabilities=[str(v) for v in (info.get("capabilities") or [])],
                )
            )
        out.sort(key=lambda x: x.name)
        return out

    def load_skill(self, skill_name: str) -> str:
        return self._mgr.load_skill(skill_name)

    def read_skill_file(self, skill_name: str, filename: str) -> str:
        return self._mgr.read_skill_file(skill_name, filename)

    def execute_skill_script(self, skill_name: str, script_name: str, args: str) -> str:
        return self._mgr.execute_skill_script(skill_name, script_name, args=args)
