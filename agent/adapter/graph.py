"""LangGraph 工作流组装模块。"""

from __future__ import annotations

import os

from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.telemetry import emit_event


def create_system_prompt(skill_manager) -> str:
    """构造每次模型调用都会注入的 system prompt。"""
    return (
        "你是一个有帮助的智能助手。\n\n"
        "重要规则：\n"
        "1. 优先直接回答用户问题；如果问题依赖项目内知识库，请先检索再回答。\n"
        "2. 工具调用必须使用 function calling，不要在文本中伪造工具调用。\n"
        "3. 始终使用中文回复。\n"
        "4. 每次回复都必须包含实际内容。\n\n"
        "可用工具：\n"
        "- load_skill(skill_name)：查看某个 skill 的完整说明。\n"
        "- read_skill_file(skill_name, filename)：读取 skill 的附加资料。\n"
        "- execute_skill_script(skill_name, script_name, args)：仅在需要直接控制某个底层脚本时使用。\n"
        "- get_retrieval_plan_schema()：获取检索计划模块的 JSON schema。\n"
        "- run_retrieval_plan(query, plan_json, group_id='', doc_id='')：执行你自己制定的检索计划。这个工具不会替你判断问题类型；你需要先依据 skill 说明决定检索模式、组合方式、验证步骤，再把计划交给它执行。\n\n"
        "处理知识库问题时请遵循：\n"
        "1. 先 load_skill('rag-answering') 或 load_skill('rag-retrieval')，理解当前支持哪些检索模式、如何组合、如何验证。\n"
        "2. 如果需要，先调用 get_retrieval_plan_schema()，再按 schema 组织 plan_json。\n"
        "3. 由你自己判断问题属于什么检索类型，是否需要多步检索，是否需要验证回查。\n"
        "4. 把你的判断写成 plan_json，再调用 run_retrieval_plan 执行。\n"
        "5. 回答时优先引用 run_retrieval_plan 返回 items 中的 document_name、chunk_id、text 等证据字段。\n"
        "6. 如果证据不足，要明确说明，而不是猜测。\n\n"
        f"{skill_manager.get_skills_prompt()}"
    )


def build_graph(*, model, tools, system_prompt: str):
    """组装 Agent -> Tools -> Agent 的 LangGraph 循环。"""

    def agent_node(state: MessagesState):
        bound_model = model.bind_tools(tools)
        emit_event("agent.think.start", {"message_count": len(state["messages"])})

        try:
            response = bound_model.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    *state["messages"],
                ]
            )

            if os.environ.get("DEBUG"):
                print(f"\n[debug] response type: {type(response)}")
                print(f"[debug] response: {response}")
                if hasattr(response, "content"):
                    print(f"[debug] content: {response.content}")
                if hasattr(response, "tool_calls"):
                    print(f"[debug] tool_calls: {response.tool_calls}")

            tool_calls = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_calls = [
                    {
                        "id": str(call.get("id") or ""),
                        "name": str(call.get("name") or ""),
                        "args": call.get("args") or {},
                    }
                    for call in response.tool_calls
                ]
                emit_event("agent.tool_calls", {"tool_calls": tool_calls})

            emit_event(
                "agent.think.end",
                {
                    "content_preview": str(getattr(response, "content", "") or "")[:240],
                    "tool_call_count": len(tool_calls),
                },
            )
            return {"messages": [response]}

        except Exception as exc:
            print(f"\nagent_node error: {exc}")
            import traceback

            traceback.print_exc()
            emit_event("agent.error", {"error": str(exc)})
            raise

    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_edge("tools", "agent")
    return workflow.compile()
