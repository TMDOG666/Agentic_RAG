"""SkillManager 的 tool 暴露层。

这里不承载复杂业务逻辑，只负责把底层能力包装成 Agent 可调用的工具。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.telemetry import emit_event
from agent.tools.retrieval_plan import execute_retrieval_plan, get_plan_schema


def create_tools(skill_manager):
    """基于 SkillManager 创建一组可供 Agent 调用的 tools。"""

    @tool
    def load_skill(skill_name: str) -> str:
        """加载某个 skill 的正文说明。"""
        print(f"[tool] load_skill: {skill_name}")
        emit_event("skill.load.start", {"skill_name": skill_name})
        content = skill_manager.load_skill(skill_name)
        emit_event(
            "skill.load.end",
            {"skill_name": skill_name, "content_preview": str(content or "")[:240]},
        )
        return content

    @tool
    def read_skill_file(skill_name: str, filename: str) -> str:
        """读取某个 skill 目录下的引用文件。"""
        print(f"[tool] read_skill_file: {skill_name}/{filename}")
        emit_event("skill.file.start", {"skill_name": skill_name, "filename": filename})
        content = skill_manager.read_skill_file(skill_name, filename)
        emit_event(
            "skill.file.end",
            {
                "skill_name": skill_name,
                "filename": filename,
                "content_preview": str(content or "")[:240],
            },
        )
        return content

    @tool
    def execute_skill_script(
        skill_name: str,
        script_name: str,
        args: str = "",
        script_args: str = "",
        **kwargs,
    ) -> str:
        """执行某个 skill 下的脚本。"""
        v_args = kwargs.get("v__args", "")
        effective_args = args or script_args or v_args
        print(f"[tool] execute_skill_script: {skill_name}/{script_name} {effective_args}")
        emit_event(
            "skill.script.start",
            {
                "skill_name": skill_name,
                "script_name": script_name,
                "script_args": effective_args,
            },
        )
        content = skill_manager.execute_skill_script(skill_name, script_name, effective_args)
        emit_event(
            "skill.script.end",
            {
                "skill_name": skill_name,
                "script_name": script_name,
                "script_args": effective_args,
                "content_preview": str(content or "")[:240],
            },
        )
        return content

    @tool
    def get_retrieval_plan_schema() -> str:
        """返回检索计划模块的 JSON schema。"""
        emit_event("tool.start", {"tool_name": "get_retrieval_plan_schema"})
        content = json.dumps(get_plan_schema(), ensure_ascii=False)
        emit_event(
            "tool.end",
            {
                "tool_name": "get_retrieval_plan_schema",
                "content_preview": content[:240],
            },
        )
        return content

    @tool
    def run_retrieval_plan(
        query: str,
        plan_json: str,
        group_id: str = "",
        doc_id: str = "",
    ) -> str:
        """执行检索计划，并返回统一的证据结果。"""
        try:
            emit_event(
                "tool.start",
                {
                    "tool_name": "run_retrieval_plan",
                    "query": query,
                    "group_id": group_id,
                    "doc_id": doc_id,
                },
            )
            result = execute_retrieval_plan(
                skill_manager=skill_manager,
                query=query,
                plan_json=plan_json,
                group_id=group_id,
                doc_id=doc_id,
            )
            content = json.dumps(result, ensure_ascii=False)
            emit_event(
                "tool.end",
                {
                    "tool_name": "run_retrieval_plan",
                    "steps": len(result.get("steps") or []),
                    "items": len(result.get("items") or []),
                    "errors": len(result.get("errors") or []),
                    "items_preview": (result.get("items") or [])[:8],
                },
            )
            return content
        except Exception as exc:
            emit_event(
                "tool.error",
                {
                    "tool_name": "run_retrieval_plan",
                    "error": str(exc),
                },
            )
            return f"检索计划执行失败: {exc}"

    return [
        load_skill,
        read_skill_file,
        execute_skill_script,
        get_retrieval_plan_schema,
        run_retrieval_plan,
    ]
