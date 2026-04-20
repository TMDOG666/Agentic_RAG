"""Agent token usage helpers."""

from __future__ import annotations

from typing import Any


def estimate_text_tokens(text: str) -> int:
    """用保守的字符近似法估算 token。

    中文场景下 1 个汉字通常接近 1 个 token，英文按 4 字符约 1 token 做粗略估算。
    """
    content = str(text or "").strip()
    if not content:
        return 0
    non_ascii = sum(1 for ch in content if ord(ch) > 127)
    ascii_chars = len(content) - non_ascii
    return max(1, non_ascii + (ascii_chars + 3) // 4)


def estimate_message_tokens(messages: list[Any]) -> int:
    total = 0
    for message in messages or []:
        if isinstance(message, dict):
            total += estimate_text_tokens(message.get("content") or "")
            total += estimate_text_tokens(message.get("role") or "")
            continue
        content = getattr(message, "content", "")
        role = getattr(message, "type", "") or getattr(message, "role", "")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    total += estimate_text_tokens(item.get("text") or "")
                else:
                    total += estimate_text_tokens(str(item))
        else:
            total += estimate_text_tokens(str(content or ""))
        total += estimate_text_tokens(str(role or ""))
    return total


def extract_usage_metadata(response: Any) -> dict[str, Any]:
    """从 LangChain/OpenAI-compatible 响应中提取 usage。"""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage:
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "source": "usage_metadata",
        }

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, dict) and token_usage:
            return {
                "input_tokens": int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0),
                "output_tokens": int(token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0),
                "total_tokens": int(token_usage.get("total_tokens") or 0),
                "source": "response_metadata",
            }

    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "source": "estimated",
    }

