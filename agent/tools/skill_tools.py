"""SkillManager 的 tool 暴露层。

这里不承载复杂业务逻辑，只负责把底层能力包装成 Agent 可调用的工具。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.tools.retrieval_plan import execute_retrieval_plan, get_plan_schema


def create_tools(skill_manager):
    """基于 SkillManager 创建一组可供 Agent 调用的 tools。"""

    @tool
    def load_skill(skill_name: str) -> str:
        """加载某个 skill 的正文说明。"""
        print(f"[tool] load_skill: {skill_name}")
        return skill_manager.load_skill(skill_name)

    @tool
    def read_skill_file(skill_name: str, filename: str) -> str:
        """读取某个 skill 目录下的引用文件。"""
        print(f"[tool] read_skill_file: {skill_name}/{filename}")
        return skill_manager.read_skill_file(skill_name, filename)

    @tool
    def execute_skill_script(
        skill_name: str,
        script_name: str,
        args: str = "",
        script_args: str = "",
        **kwargs,
    ) -> str:
        """执行某个 skill 下的脚本。"""
        # 兼容历史参数名，避免不同提示词版本传参不一致。
        v_args = kwargs.get("v__args", "")
        effective_args = args or script_args or v_args
        print(f"[tool] execute_skill_script: {skill_name}/{script_name} {effective_args}")
        return skill_manager.execute_skill_script(skill_name, script_name, effective_args)

    @tool
    def get_retrieval_plan_schema() -> str:
        """返回检索计划模块的 JSON schema。"""
        return json.dumps(get_plan_schema(), ensure_ascii=False)

    @tool
    def run_retrieval_plan(
        query: str,
        plan_json: str,
        group_id: str = "",
        doc_id: str = "",
    ) -> str:
        """执行检索计划，并返回统一的证据结果。"""
        try:
            result = execute_retrieval_plan(
                skill_manager=skill_manager,
                query=query,
                plan_json=plan_json,
                group_id=group_id,
                doc_id=doc_id,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"检索计划执行失败: {exc}"

    return [
        load_skill,
        read_skill_file,
        execute_skill_script,
        get_retrieval_plan_schema,
        run_retrieval_plan,
    ]
