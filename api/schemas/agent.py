from __future__ import annotations

"""api.schemas.agent

Agent 相关的 Pydantic schema。

说明：
- schema 负责定义 API 层的入参/出参结构。
- 这里刻意只暴露最小字段，避免将底层 agent 的复杂状态直接泄露到 HTTP 层。
"""

from typing import Optional

from pydantic import BaseModel


class AgentRunIn(BaseModel):
    """Agent 运行入参。"""

    # 用户输入的自然语言。
    user_text: str

    # 可选：在 API 层注入的一段前缀文本。
    # 常用于：追加业务约束、system 指令、或调试信息。
    prefix: Optional[str] = None


class AgentRunOut(BaseModel):
    """Agent 运行出参。"""

    # agent 的最终回复文本。
    reply: str
