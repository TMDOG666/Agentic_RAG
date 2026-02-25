"""grag.graph_construction.chunker

文本分块器（Text Chunker）

职责：
- 将原始文本文档拆分为适合后续图谱构建（实体抽取/关系抽取/向量化）的 Chunk 列表
- 尽可能按“语义结构”拆分，而不是简单按固定字符数或分隔符

核心策略：递归分层与贪婪合并（Recursive Layering and Greedy Merging）
- 分层递归切分：优先识别文档结构标题（Markdown/中文章节/法律条款等），从高到低递归切分
- 上下文感知合并：对过短的块进行向上贪婪合并，同时遵守 max/min 阈值
- 健壮回退：当没有任何结构化标记时，降级为传统分割（\n\n -> \n -> 句子 -> 固定步长）
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Callable, List, Optional, Sequence, Tuple
from grag.monitoring.monitoring_manager import get_current_monitor
from ..config import get_config_manager

def _default_token_counter(text: str) -> int:
    """默认 token 计数器。
    说明：
        - 英文/数字以连续字母数字串计 1 token
        - 中文以单个汉字计 1 token
        - 该计数是“粗略估算”，用于 chunk 大小控制，而非严格等同于 LLM tokenizer。
    """
    text = text.strip()
    if not text:
        return 0
    return len(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text))

class SemanticChunker:
    """语义分块器。

    对外接口为 :meth:`chunk`，输入文本字符串，输出 ``List[str]`` chunks。
    """

    def __init__(
        self,
        max_token_threshold: Optional[int] = None,
        min_token_threshold: Optional[int] = None,
        token_counter: Optional[Callable[[str], int]] = None,
        preserve_headings: Optional[bool] = None,
        enable_fallback: Optional[bool] = None,
        fallback_fixed_step_chars: Optional[int] = None,
    ) -> None:
        """初始化分块器。

        Args:
            max_token_threshold: 单块最大 token 阈值
            min_token_threshold: 单块最小 token 阈值
            token_counter: 自定义 token 计数器
            preserve_headings: 是否保留标题
            enable_fallback: 是否启用回退机制
            fallback_fixed_step_chars: 回退机制固定步长（字符数）
        """
        settings = get_config_manager().get_settings()

        cfg = settings.graph_construction.chunking

        def _get_value(key: str, default):
            if cfg is None:
                return default
            if isinstance(cfg, dict):
                return cfg.get(key, default)
            return getattr(cfg, key, default)

        resolved_max = (
            max_token_threshold if max_token_threshold is not None else _get_value("max_token_threshold", None)
        )
        if resolved_max is None:
            # legacy
            resolved_max = _get_value("chunk_size", 512)
        resolved_min = min_token_threshold if min_token_threshold is not None else _get_value("min_token_threshold", 128)
        resolved_preserve = preserve_headings if preserve_headings is not None else _get_value("preserve_headings", True)
        resolved_enable_fallback = enable_fallback if enable_fallback is not None else _get_value("enable_fallback", True)
        resolved_fallback_step = (
            fallback_fixed_step_chars
            if fallback_fixed_step_chars is not None
            else _get_value("fallback_fixed_step_chars", None)
        )
        resolved_fallback_step = int(resolved_fallback_step) if resolved_fallback_step is not None else None

        if resolved_max <= 0:
            raise ValueError("max_token_threshold must be > 0")
        if resolved_min <= 0:
            raise ValueError("min_token_threshold must be > 0")
        if resolved_min > resolved_max:
            raise ValueError("min_token_threshold must be <= max_token_threshold")

        self.config = SimpleNamespace(
            max_token_threshold=int(resolved_max),
            min_token_threshold=int(resolved_min),
            preserve_headings=bool(resolved_preserve),
            enable_fallback=bool(resolved_enable_fallback),
            fallback_fixed_step_chars=resolved_fallback_step,
        )

        self._token_counter = token_counter or _default_token_counter

        self._heading_patterns: Sequence[Tuple[int, re.Pattern[str]]] = (
            (1, re.compile(r"^(?P<h>#)\s+.+$", re.MULTILINE)),
            (2, re.compile(r"^(?P<h>##)\s+.+$", re.MULTILINE)),
            (3, re.compile(r"^(?P<h>###)\s+.+$", re.MULTILINE)),
            (4, re.compile(r"^(?P<h>####)\s+.+$", re.MULTILINE)),
            (5, re.compile(r"^(?P<h>#####)\s+.+$", re.MULTILINE)),
            (6, re.compile(r"^(?P<h>######)\s+.+$", re.MULTILINE)),
            (1, re.compile(r"^第[一二三四五六七八九十百千万0-9]+章\s*.*$", re.MULTILINE)),
            (2, re.compile(r"^第[一二三四五六七八九十百千万0-9]+节\s*.*$", re.MULTILINE)),
            (3, re.compile(r"^（[一二三四五六七八九十百千万0-9]+）\s*.*$", re.MULTILINE)),
            (2, re.compile(r"^\d+(?:\.\d+)*[\.)]\s+.+$", re.MULTILINE)),
            (3, re.compile(r"^[a-zA-Z][\.)]\s+.+$", re.MULTILINE)),
        )

    def chunk(self, text: str) -> List[str]:
        """对文本进行语义分块。

        工作流：
        1) 结构识别：若存在标题结构，进入递归分层切分
        2) 贪婪合并：将过短块合并，避免“孤儿信息”
        3) 回退机制：无标题结构时，使用传统分隔符分割
        """
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.strip("\n")
        if not text.strip():
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.observe("chunking.input_chars", 0.0)
                monitor.observe("chunking.output_chunks", 0.0)
            return []

        monitor = get_current_monitor()
        if monitor is not None:
            monitor.observe("chunking.input_chars", float(len(text)))

        if not self._has_any_heading(text):
            if self.config.enable_fallback:
                out = self._fallback_chunk(text)
                if monitor is not None:
                    monitor.observe("chunking.output_chunks", float(len(out)))
                return out
            out = [text.strip()] if text.strip() else []
            if monitor is not None:
                monitor.observe("chunking.output_chunks", float(len(out)))
            return out

        raw = self._recursive_split(text)
        raw = [c.strip("\n") for c in raw if c and c.strip()]
        out = self._greedy_merge(raw)
        if monitor is not None:
            monitor.observe("chunking.output_chunks", float(len(out)))
        return out

    def _has_any_heading(self, text: str) -> bool:
        """判断文本中是否存在可识别的结构化标题。"""
        for _, pat in self._heading_patterns:
            if pat.search(text):
                return True
        return False

    def _recursive_split(self, text: str) -> List[str]:
        """递归分层切分。

        先收集“当前文本中出现过的标题层级”，再按层级从高到低递归拆分。
        """
        levels_present = sorted({lvl for lvl, pat in self._heading_patterns if pat.search(text)})
        if not levels_present:
            return [text]

        def split_at_level(segment: str, level: int) -> List[str]:
            spans: List[Tuple[int, int]] = []
            for lvl, pat in self._heading_patterns:
                if lvl != level:
                    continue
                for m in pat.finditer(segment):
                    spans.append((m.start(), m.end()))
            if not spans:
                return [segment]
            spans.sort(key=lambda x: x[0])
            starts = [s for s, _ in spans]
            out: List[str] = []
            for i, start in enumerate(starts):
                end = starts[i + 1] if i + 1 < len(starts) else len(segment)
                out.append(segment[start:end])
            if starts[0] > 0:
                prefix = segment[: starts[0]]
                if prefix.strip():
                    out.insert(0, prefix)
            return out

        def rec(seg: str, level_index: int) -> List[str]:
            if level_index >= len(levels_present):
                return [seg]
            parts = split_at_level(seg, levels_present[level_index])
            if len(parts) == 1:
                return rec(seg, level_index + 1)
            out: List[str] = []
            for p in parts:
                out.extend(rec(p, level_index + 1))
            return out

        return rec(text, 0)

    def _greedy_merge(self, chunks: Sequence[str]) -> List[str]:
        """上下文感知贪婪合并。

        将递归切分的 raw chunks 按 max/min 阈值进行合并：
        - 过短 chunk 会尽量向上合并到前一个 chunk
        - 单块尽量不超过 max_token_threshold
        """
        max_t = self.config.max_token_threshold
        min_t = self.config.min_token_threshold

        final: List[str] = []
        current = ""

        def cur_tokens() -> int:
            return self._token_counter(current)

        for i, ch in enumerate(chunks):
            ch = ch.strip("\n")
            if not ch.strip():
                continue

            candidate = (current + "\n\n" + ch) if current else ch
            cand_tokens = self._token_counter(candidate)

            if current and cand_tokens > max_t and cur_tokens() >= min_t:
                final.append(current.strip())
                current = ch
                continue

            current = candidate

            is_last = i == len(chunks) - 1
            if is_last and current.strip():
                final.append(current.strip())
                current = ""

        if current.strip():
            final.append(current.strip())

        merged: List[str] = []
        for ch in final:
            if not merged:
                merged.append(ch)
                continue
            if self._token_counter(ch) < min_t and self._token_counter(merged[-1] + "\n\n" + ch) <= max_t:
                merged[-1] = (merged[-1] + "\n\n" + ch).strip()
            else:
                merged.append(ch)
        return merged

    def _fallback_chunk(self, text: str) -> List[str]:
        """无结构回退：生成基础切分单元后复用贪婪合并逻辑。"""
        units = self._fallback_units(text)
        return self._greedy_merge(units)

    def _fallback_units(self, text: str) -> List[str]:
        """生成回退分割的基础单元。

        优先级：段落（\n\n）-> 行（\n）-> 句子 -> 固定步长。
        """
        text = text.strip("\n")
        if not text.strip():
            return []

        blocks = [b for b in text.split("\n\n") if b.strip()]
        if len(blocks) > 1:
            return blocks

        lines = [l for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            return lines

        sentences = [s.strip() for s in re.split(r"(?<=[\.!\?。！？])\s+", text) if s.strip()]
        if len(sentences) > 1:
            return sentences

        step = self.config.fallback_fixed_step_chars or max(200, int(self.config.max_token_threshold * 4))
        return [text[i : i + step] for i in range(0, len(text), step) if text[i : i + step].strip()]


def chunk_text(
    text: str,
) -> List[str]:
    """便捷函数：一次性分块。"""
    return SemanticChunker().chunk(text)

