"""LangGraph workflow assembly with lightweight message sanitization."""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.telemetry import emit_event
from agent.token_usage import estimate_message_tokens, estimate_text_tokens, extract_usage_metadata
from grag.observability import get_current_trace_recorder

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def create_system_prompt(skill_manager) -> str:
    """Create the system prompt injected into each model call."""
    return (
        "你是一个有帮助的智能助手。\n\n"
        "重要规则：\n"
        "1. 优先直接回答用户问题；如果问题依赖项目内知识库，请先检索再回答。\n"
        "2. 工具调用必须使用 function calling，不要在文本中伪造工具调用。\n"
        "3. 始终使用中文回复。\n"
        "4. 每次回复都必须包含实际内容。\n\n"
        "可用工具：\n"
        "- load_skill(skill_name)：查看某个 skill 的紧凑说明。\n"
        "- read_skill_file(skill_name, filename)：读取 skill 的附加资料。\n"
        "- execute_skill_script(skill_name, script_name, args)：仅在需要直接控制某个底层脚本时使用。\n"
        "- get_retrieval_plan_schema()：获取检索计划模块的 JSON schema。\n"
        "- run_retrieval_plan(query, plan_json, group_id='', doc_id='')：执行你自己制定的检索计划，返回紧凑证据视图和 result_id。\n"
        "- get_retrieval_result(result_id, max_items=5)：按 result_id 取回此前检索结果的紧凑视图。\n\n"
        "处理知识库问题时请遵循：\n"
        "1. 先 load_skill('rag-answering') 或 load_skill('rag-retrieval')，理解当前支持哪些检索模式、如何组合、如何验证。\n"
        "2. 如有需要，先调用 get_retrieval_plan_schema()，再按 schema 组织 plan_json。\n"
        "3. 由你自己判断问题属于什么检索类型，是否需要多步检索，是否需要验证回查。\n"
        "4. 把你的判断写成 plan_json，再调用 run_retrieval_plan 执行。\n"
        "5. 回答时优先引用 run_retrieval_plan 返回 items 中的 document_name、chunk_id、text 等证据字段。\n"
        "6. 如果证据不足，要明确说明，而不是猜测。\n\n"
        f"{skill_manager.get_skills_prompt()}"
    )


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "type", "") or getattr(message, "role", "") or "")


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", "")

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content or "")


def _remove_think_blocks(text: str) -> str:
    return THINK_BLOCK_RE.sub("", str(text or "")).strip()


def _remove_duplicate_lines(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    compact_lines: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = line.strip()
        if not normalized:
            if compact_lines and compact_lines[-1] != "":
                compact_lines.append("")
            continue
        if normalized in seen:
            continue
        compact_lines.append(line)
        seen.add(normalized)
    return "\n".join(compact_lines).strip()


def _sanitize_text(text: str) -> str:
    return _remove_duplicate_lines(_remove_think_blocks(text))


def _compact_messages(messages: list[Any]) -> list[Any]:
    compacted: list[Any] = []
    seen_pairs: set[tuple[str, str]] = set()

    for message in messages or []:
        role = _message_role(message) or "user"
        content = _sanitize_text(_message_content(message))
        if isinstance(message, dict):
            cloned = dict(message)
            cloned["content"] = content
            if cloned.get("role") == "tool":
                compacted.append(cloned)
                continue
            if not content:
                continue
            pair = (role, content)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            compacted.append(cloned)
            continue

        if isinstance(message, ToolMessage):
            tool_content = content or _message_content(message)
            compacted.append(
                ToolMessage(
                    content=tool_content,
                    tool_call_id=message.tool_call_id,
                    name=getattr(message, "name", None),
                    artifact=getattr(message, "artifact", None),
                    additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                    response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                    id=getattr(message, "id", None),
                )
            )
            continue

        if isinstance(message, AIMessage):
            if getattr(message, "tool_calls", None):
                compacted.append(
                    AIMessage(
                        content=content,
                        tool_calls=list(getattr(message, "tool_calls", []) or []),
                        invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
                        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                        name=getattr(message, "name", None),
                        id=getattr(message, "id", None),
                    )
                )
                continue
            if not content:
                continue
            pair = (role, content)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            compacted.append(
                AIMessage(
                    content=content,
                    tool_calls=list(getattr(message, "tool_calls", []) or []),
                    invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
                    additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                    response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                    name=getattr(message, "name", None),
                    id=getattr(message, "id", None),
                )
            )
            continue

        if isinstance(message, HumanMessage):
            if not content:
                continue
            pair = (role, content)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            compacted.append(
                HumanMessage(
                    content=content,
                    additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                    response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                    name=getattr(message, "name", None),
                    id=getattr(message, "id", None),
                )
            )
            continue

        if isinstance(message, SystemMessage):
            if not content:
                continue
            pair = (role, content)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            compacted.append(
                SystemMessage(
                    content=content,
                    additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                    response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                    name=getattr(message, "name", None),
                    id=getattr(message, "id", None),
                )
            )
            continue

        compacted.append(message)

    return compacted


def build_graph(*, model, tools, system_prompt: str):
    """Assemble the Agent -> Tools -> Agent LangGraph loop."""

    def agent_node(state: MessagesState):
        bound_model = model.bind_tools(tools)
        invocation_id = f"agent-think:{uuid.uuid4().hex[:10]}"
        recorder = get_current_trace_recorder()
        sanitized_messages = _compact_messages(list(state.get("messages") or []))
        request_messages = [{"role": "system", "content": system_prompt}, *sanitized_messages]
        started_at = time.perf_counter()

        if recorder is not None:
            recorder.start_invocation(
                kind="llm",
                name="agent.think",
                invocation_id=invocation_id,
                input_payload={
                    "message_count": len(sanitized_messages),
                    "messages_preview": [_message_content(msg)[:240] for msg in sanitized_messages[-4:]],
                },
                metadata={
                    "model_name": getattr(model, "model_name", None) or getattr(model, "model", None),
                    "provider": getattr(model, "openai_api_base", None) or getattr(model, "base_url", None),
                },
            )

        emit_event(
            "agent.think.start",
            {
                "task_id": invocation_id,
                "message_count": len(sanitized_messages),
                "model_name": getattr(model, "model_name", None) or getattr(model, "model", None),
                "provider": getattr(model, "openai_api_base", None) or getattr(model, "base_url", None),
            },
        )

        try:
            response = bound_model.invoke(request_messages)

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

            usage = extract_usage_metadata(response)
            response_content = _message_content(response)
            input_tokens = usage["input_tokens"] or estimate_message_tokens(request_messages)
            output_tokens = usage["output_tokens"] or estimate_text_tokens(response_content)
            total_tokens = usage["total_tokens"] or (input_tokens + output_tokens)
            emit_event(
                "usage.llm",
                {
                    "task_id": invocation_id,
                    "provider": getattr(model, "openai_api_base", None) or getattr(model, "base_url", None),
                    "model_name": getattr(model, "model_name", None) or getattr(model, "model", None),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "is_estimated": usage["source"] == "estimated",
                    "usage_source": usage["source"],
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )

            if recorder is not None:
                recorder.finish_invocation(
                    invocation_id,
                    status="completed",
                    output_payload={
                        "content_preview": _sanitize_text(response_content)[:1000],
                        "tool_calls": tool_calls,
                    },
                    usage={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "usage_source": usage["source"],
                        "is_estimated": usage["source"] == "estimated",
                    },
                    metadata={
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                )

            emit_event(
                "agent.think.end",
                {
                    "task_id": invocation_id,
                    "content_preview": _sanitize_text(response_content)[:240],
                    "tool_call_count": len(tool_calls),
                },
            )
            return {"messages": [response]}

        except Exception as exc:
            print(f"\nagent_node error: {exc}")
            import traceback

            traceback.print_exc()
            if recorder is not None:
                recorder.finish_invocation(
                    invocation_id,
                    status="failed",
                    error={
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    metadata={
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                )
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
