from __future__ import annotations

"""grag.retrieval.utils.query_decomposition

查询拆分（Query Decomposition）。

本模块用于支持 LightRAG 风格的两层检索入口：
- global：以“高层主题词（high）”为入口做图检索扩展
- local：以“低层具体实体（low）”为入口做图检索扩展

当前实现是规则版（无 LLM）：
- 如果输入包含 `A>B>C`，认为 high=A、low=C
- 如果输入包含 `A/B/C`，认为 high=A、low=C
- 否则按空白切分：high=第一个 token、low=最后一个 token

注意：
- 规则拆分是可解释但不一定准确的启发式；如果你未来接入 LLM 抽取实体层级，
  可以在保持函数签名不变的前提下替换内部策略。
"""

from typing import Tuple


def split_high_low(text: str) -> Tuple[str, str]:
    """将输入拆分为 (high, low)。

    Args:
        text: 用户输入/实体层级字符串。

    Returns:
        (high, low)
        - high：高层主题/父级实体（用于 global）
        - low：低层具体实体/子级实体（用于 local）
    """
    s = (text or "").strip()
    if not s:
        return "", ""

    if ">" in s:
        parts = [p.strip() for p in s.split(">") if p.strip()]
    elif "/" in s:
        parts = [p.strip() for p in s.split("/") if p.strip()]
    else:
        parts = [p for p in s.split() if p]

    if not parts:
        return "", ""

    return parts[0], parts[-1]
