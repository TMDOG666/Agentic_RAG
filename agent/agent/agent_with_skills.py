"""Agent 层：对外运行入口。"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Optional

from agent.adapter.runtime import create_runtime
from agent.telemetry import bind_event_sink, emit_event

_RUNTIME = None


def _get_runtime() -> dict:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = create_runtime()
    return _RUNTIME


def _chunk_text(text: str, size: int = 48) -> list[str]:
    content = str(text or "")
    if not content:
        return []
    return [content[i : i + size] for i in range(0, len(content), size)]


def _extract_message_content(message: Any) -> str:
    if hasattr(message, "content"):
        content = message.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content or "")
    return str(message or "")


def _invoke_graph(user_text: str) -> tuple[list[Any], str]:
    runtime = _get_runtime()
    graph = runtime["graph"]
    result = graph.invoke({"messages": [{"role": "user", "content": user_text}]})
    messages = list(result.get("messages") or [])
    final_text = _extract_message_content(messages[-1]) if messages else ""
    return messages, final_text


def run_once(user_text: str) -> str:
    max_retries = int(os.environ.get("API_RETRY_MAX", "5"))
    base_sleep = float(os.environ.get("API_RETRY_BASE_SLEEP", "2"))

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            _messages, content = _invoke_graph(user_text)
            if not content.strip():
                return "模型返回了空内容，请检查 API Key 或模型服务是否正常。"
            return content
        except Exception as exc:
            last_error = exc
            error_msg = str(exc)
            print(f"\n错误详情: {error_msg}")

            lowered = error_msg.lower()
            is_rate_limited = (
                "rate" in lowered
                or "quota" in lowered
                or "tpm" in lowered
                or "429" in lowered
                or "rate limit" in lowered
            )
            if is_rate_limited and attempt < max_retries - 1:
                sleep_s = base_sleep * (2**attempt)
                print(f"\n检测到限流，{sleep_s:.1f}s 后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(sleep_s)
                continue

            if "api_key" in lowered or "authentication" in lowered:
                return "API Key 错误，请检查环境变量是否正确配置。"
            if "connection" in lowered or "timeout" in lowered:
                return "网络连接失败，请检查模型服务或网络状态。"
            if is_rate_limited:
                return "API 调用超出限制，请稍后再试。"
            return f"发生错误: {error_msg}"

    return f"发生错误: {last_error}"


def stream_once(user_text: str, on_event: Callable[[dict[str, Any]], None]) -> str:
    final_text = ""
    with bind_event_sink(on_event):
        emit_event("run.start", {"query": user_text})
        try:
            _messages, final_text = _invoke_graph(user_text)
            if not final_text.strip():
                final_text = "模型返回了空内容。"

            emit_event("assistant.start", {})
            for chunk in _chunk_text(final_text):
                emit_event("assistant.chunk", {"delta": chunk})
            emit_event("assistant.done", {"content": final_text})
            emit_event("run.complete", {"reply_chars": len(final_text)})
            return final_text
        except Exception as exc:
            error_text = f"发生错误: {exc}"
            emit_event("agent.error", {"error": str(exc)})
            emit_event("assistant.start", {})
            emit_event("assistant.chunk", {"delta": error_text})
            emit_event("assistant.done", {"content": error_text})
            emit_event("run.failed", {"error": str(exc)})
            return error_text


def _extract_first_json(text: str) -> Any:
    if not text:
        raise ValueError("Empty response")

    start_candidates = [i for i, ch in enumerate(text) if ch in "[{"]
    if not start_candidates:
        raise ValueError(f"No JSON start found in response: {text[:200]}")

    start = start_candidates[0]
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text[start:])
        return obj
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON from response: {text[:200]}") from exc


def run_once_json(prompt: str, *, max_retries: int = 3, base_sleep: float = 1.0) -> Any:
    last_raw = ""
    for attempt in range(max_retries):
        raw = run_once(prompt)
        last_raw = raw or ""
        try:
            return _extract_first_json(last_raw)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(base_sleep * (2**attempt))
                continue
            raise


def main():
    print("\n" + "=" * 60)
    print("Agent Skills 智能助手")
    print("=" * 60)
    print("提示：输入 'exit' 或 'quit' 退出")
    print("提示：输入 'skills' 查看可用技能")
    print("提示：输入 'test' 测试 API 连接")
    print("提示：输入 'debug' 开启调试模式")
    print("=" * 60)

    runtime = _get_runtime()
    skill_manager = runtime["skill_manager"]
    model = runtime["model"]
    agent_config = runtime["agent_config"]

    provider = os.environ.get("AGENT_PROVIDER") or (agent_config.get("provider") if isinstance(agent_config, dict) else None) or "siliconflow"
    providers = (agent_config.get("providers") if isinstance(agent_config, dict) else None) or {}
    pconf = providers.get(provider) or {}
    api_key_env = pconf.get("api_key_env") or ("SILICONFLOW_API_KEY" if provider == "siliconflow" else "OPENAI_API_KEY")
    base_url = os.environ.get("AGENT_BASE_URL") or pconf.get("base_url")
    if not base_url and provider == "siliconflow":
        base_url = os.environ.get("SILICONFLOW_BASE_URL")

    api_key = os.environ.get("AGENT_API_KEY") or os.environ.get(api_key_env)
    if not api_key and provider == "siliconflow":
        api_key = os.environ.get("SILICONFLOW_API_KEY")

    is_local = bool(base_url) and ("localhost" in str(base_url) or "127.0.0.1" in str(base_url))
    if not api_key and not is_local:
        print(f"\n警告：未检测到 API Key 环境变量（provider={provider}, env={api_key_env}）")
        print(f"- set {api_key_env}=your_key")
        print("或使用 AGENT_API_KEY 覆盖\n")
    elif api_key:
        print(f"\nAPI Key 已设置（前 10 位）: {api_key[:10]}...\n")

    debug_mode = False

    while True:
        try:
            user_text = input("你> ").strip()
            if not user_text:
                continue

            if user_text.lower() in {"exit", "quit", "退出"}:
                print("\n再见")
                break

            if user_text.lower() == "debug":
                debug_mode = not debug_mode
                if debug_mode:
                    os.environ["DEBUG"] = "1"
                    print("\n调试模式已开启\n")
                else:
                    os.environ.pop("DEBUG", None)
                    print("\n调试模式已关闭\n")
                continue

            if user_text.lower() == "skills":
                print("\n可用技能：")
                for name, info in skill_manager.skills_metadata.items():
                    print(f" - {name}: {info['description']}")
                print()
                continue

            if user_text.lower() == "test":
                print("\n测试 API 连接...")
                try:
                    test_response = model.invoke([{"role": "user", "content": "你好"}])
                    print(f"API 连接正常，模型回复: {_extract_message_content(test_response)[:50]}...")
                except Exception as exc:
                    print(f"API 连接失败: {exc}")
                print()
                continue

            print()
            answer = run_once(user_text)
            print(f"助手: {answer}\n")
        except KeyboardInterrupt:
            print("\n\n再见")
            break
        except Exception as exc:
            print(f"\n错误: {exc}\n")


if __name__ == "__main__":
    main()
