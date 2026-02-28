from __future__ import annotations

"""api.services.skills_service

SkillsService：skills 管理业务层。

底层依赖：
- `agent.skill.manager.SkillManager`

职责：
- 将 SkillManager 的返回结果（通常是 str 或内部 dict）转换为 API 友好的结构。
- controller 层只负责 HTTP 参数接收。
"""

from agent.skill.manager import SkillManager

from api.schemas.skills import SkillOut


class SkillsService:
    """skills 管理服务。"""

    def __init__(self) -> None:
        """初始化 SkillManager。

        注意：
        - SkillManager 初始化会扫描 skills 目录并打印日志。
        - 这属于当前项目的预期行为（便于本地调试）。
        """
        self._mgr = SkillManager()

    def list_skills(self) -> list[SkillOut]:
        """列出 skills 元信息（name/description）。"""
        out: list[SkillOut] = []
        for name, info in (self._mgr.skills_metadata or {}).items():
            out.append(SkillOut(name=str(name), description=str(info.get("description") or "")))
        # 按名称排序，保证输出稳定。
        out.sort(key=lambda x: x.name)
        return out

    def load_skill(self, skill_name: str) -> str:
        """加载 skill 正文指令。"""
        return self._mgr.load_skill(skill_name)

    def read_skill_file(self, skill_name: str, filename: str) -> str:
        """读取 skill 目录内的文件内容。"""
        return self._mgr.read_skill_file(skill_name, filename)

    def execute_skill_script(self, skill_name: str, script_name: str, args: str) -> str:
        """执行 skill 脚本。

        风险提示：
        - 执行脚本属于高权限操作。
        - 当前 MVP 未做鉴权，请谨慎暴露到公网环境。
        """
        return self._mgr.execute_skill_script(skill_name, script_name, args=args)
