"""Tool wrappers for SkillManager."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.tools.retrieval_plan import execute_retrieval_plan, get_plan_schema


def create_tools(skill_manager):
    """Create LangChain tools backed by SkillManager."""

    @tool
    def load_skill(skill_name: str) -> str:
        """Load the full instruction body of a skill."""
        print(f"[tool] load_skill: {skill_name}")
        return skill_manager.load_skill(skill_name)

    @tool
    def read_skill_file(skill_name: str, filename: str) -> str:
        """Read a reference or asset file inside a skill directory."""
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
        """Execute a concrete script inside a skill directory."""
        v_args = kwargs.get("v__args", "")
        effective_args = args or script_args or v_args
        print(f"[tool] execute_skill_script: {skill_name}/{script_name} {effective_args}")
        return skill_manager.execute_skill_script(skill_name, script_name, effective_args)

    @tool
    def get_retrieval_plan_schema() -> str:
        """Return the JSON schema for the retrieval-plan module."""
        return json.dumps(get_plan_schema(), ensure_ascii=False)

    @tool
    def run_retrieval_plan(
        query: str,
        plan_json: str,
        group_id: str = "",
        doc_id: str = "",
    ) -> str:
        """Execute a retrieval plan module and return normalized evidence."""
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
