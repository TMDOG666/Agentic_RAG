import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from grag.monitoring.monitoring_manager import get_current_monitor

from ..config import get_config_manager
from ..model.llm_client import LLMClient


COREFERENCE_RESOLUTION_PROMPT = """
你是一名专业的文本编辑和指代消解专家。你的任务是识别文本中指代不清的短语，并把它们替换为更具体的实体名称。

你的输出不要使用 JSON。
请使用下面这种“标记块”格式输出，每个替换项一个块：

<|item_start|>
<|raw_start|>
原文中包含代词的短语片段
<|raw_end|>
<|result_start|>
替换后的完整短语片段
<|result_end|>
<|item_end|>

要求：
1. `raw` 必须带足够上下文，不能只输出单个“他 / 她 / 它 / 该公司”。
2. `result` 必须保留原短语中的上下文，只替换其中需要消解的部分。
3. 只输出需要替换的项；如果没有需要替换的内容，可以不输出任何标记块。
4. 即使你在标记块前后额外输出了别的文字，标记块本身也必须完整且格式正确。

示例：
<|item_start|>
<|raw_start|>
他看起来很疲惫
<|raw_end|>
<|result_start|>
警长看起来很疲惫
<|result_end|>
<|item_end|>

待处理文本：
{text}
"""


CHUNK_COREFERENCE_RESOLUTION_PROMPT = """
你是一名专业的局部指代消解编辑器。你的任务不是重写全文，而是只针对“当前文本块”内部可以明确判断的代词、简称、泛指称呼做替换。

你的输出不要使用 JSON。
请使用下面这种“标记块”格式输出，每个替换项一个块：

<|item_start|>
<|raw_start|>
当前文本块中的原片段
<|raw_end|>
<|result_start|>
替换后的片段
<|result_end|>
<|item_end|>

要求：
1. 只处理当前文本块内部能确定的指代，不要依赖全文级猜测。
2. 如果上下文不够确定，宁可不替换，也不要猜。
3. `raw` 必须带足够上下文，不能只输出单个代词。
4. 只要标记块完整即可，前后出现少量说明文字也没关系。

辅助上下文（仅用于理解，不可直接改写）：
前文摘要：
{context_before}

后文摘要：
{context_after}

当前文本块：
{text}
"""


ITEM_PATTERN = re.compile(
    r"<\|item_start\|>\s*"
    r"<\|raw_start\|>\s*(?P<raw>.*?)\s*<\|raw_end\|>\s*"
    r"<\|result_start\|>\s*(?P<result>.*?)\s*<\|result_end\|>\s*"
    r"<\|item_end\|>",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass
class DocumentWithCoreferenceResolution:
    text: str
    coreference_raw: str
    resolved_text: str
    error: Optional[str] = None


class CoreferenceResolver:
    def __init__(
        self,
        llm_chat_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        settings = get_config_manager().get_settings()
        cfg = settings.graph_construction.coreference_resolution

        def _get_value(key: str, default: Any):
            if cfg is None:
                return default
            if isinstance(cfg, dict):
                return cfg.get(key, default)
            return getattr(cfg, key, default)

        self.enabled: bool = bool(_get_value("enabled", True))
        raw_model_provider = _get_value("model_provider", settings.llm_provider)
        self.model_provider: str = str(raw_model_provider or settings.llm_provider).strip()
        self.max_distance: int = int(_get_value("max_distance", 5))
        self.max_retries: int = int(_get_value("max_retries", 3))
        self.base_sleep_seconds: float = float(_get_value("base_sleep_seconds", 2.0))

        if self.max_retries <= 0:
            raise ValueError("max_retries must be > 0")
        if self.base_sleep_seconds <= 0:
            raise ValueError("base_sleep_seconds must be > 0")

        if llm_chat_fn is not None:
            self._llm_chat_fn = llm_chat_fn
        else:
            self._llm_chat_fn = LLMClient(self.model_provider).chat

    def _build_prompt(self, text: str) -> str:
        return COREFERENCE_RESOLUTION_PROMPT.format(text=text)

    def _build_chunk_prompt(
        self,
        text: str,
        *,
        context_before: str = "",
        context_after: str = "",
    ) -> str:
        return CHUNK_COREFERENCE_RESOLUTION_PROMPT.format(
            text=text,
            context_before=(context_before or "").strip() or "无",
            context_after=(context_after or "").strip() or "无",
        )

    async def _call_llm_with_retries(self, prompt: str) -> str:
        monitor = get_current_monitor()
        if monitor is not None:
            monitor.inc("coreference_resolution.llm_calls", 1)
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                if monitor is not None:
                    monitor.inc("coreference_resolution.llm_attempts", 1)
                with (
                    monitor.span("coreference_resolution.llm_call")
                    if monitor is not None
                    else self._null_span()
                ):
                    return await asyncio.to_thread(self._llm_chat_fn, prompt)
            except Exception as exc:
                last_exc = exc
                if monitor is not None:
                    monitor.inc("coreference_resolution.llm_errors", 1)
                if attempt >= self.max_retries - 1:
                    break
                if monitor is not None:
                    monitor.inc("coreference_resolution.llm_retries", 1)
                sleep_s = self.base_sleep_seconds * (2**attempt)
                sleep_s = sleep_s + random.random() * 0.2 * sleep_s
                await asyncio.sleep(sleep_s)
        raise RuntimeError(str(last_exc) if last_exc else "LLM call failed")

    @staticmethod
    def _sanitize_llm_output(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"```(?:json|text|markdown)?", "", text, flags=re.IGNORECASE)
        text = text.replace("```", "").strip()
        return text

    @staticmethod
    def _null_span():
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()

    @classmethod
    def _parse_tagged_items(cls, raw: str) -> List[dict]:
        text = cls._sanitize_llm_output(raw)
        if not text:
            return []

        out: List[dict] = []
        for match in ITEM_PATTERN.finditer(text):
            raw_value = (match.group("raw") or "").strip()
            result_value = (match.group("result") or "").strip()
            if raw_value and result_value:
                out.append({"raw": raw_value, "result": result_value})
        return out

    @classmethod
    def _extract_json_list_text(cls, raw: str) -> str:
        text = cls._sanitize_llm_output(raw)
        if not text:
            return ""
        if text.startswith("[") and text.endswith("]"):
            return text

        start = text.find("[")
        if start < 0:
            return text

        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return text

    @classmethod
    def _parse_json_list(cls, raw: str) -> List[dict]:
        raw = cls._extract_json_list_text(raw)
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("coreference JSON must be a list")
        out: List[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_key = item.get("raw")
            if raw_key is None:
                raw_key = item.get("row")
            result = item.get("result")
            if not raw_key or result is None:
                continue
            out.append({"raw": str(raw_key), "result": str(result)})
        return out

    @classmethod
    def _parse_items(cls, raw: str) -> List[dict]:
        tagged_items = cls._parse_tagged_items(raw)
        if tagged_items:
            return tagged_items
        return cls._parse_json_list(raw)

    @staticmethod
    def _apply_replacements(text: str, items: List[dict]) -> str:
        resolved = text
        for it in items:
            raw_key = it.get("raw", "")
            result = it.get("result", "")
            if not raw_key:
                continue
            if raw_key in resolved:
                resolved = resolved.replace(raw_key, result)
        return resolved

    @classmethod
    def _normalize_raw_output(cls, raw: str) -> str:
        return cls._sanitize_llm_output(raw)

    async def resolve_text(self, text: str) -> DocumentWithCoreferenceResolution:
        if not self.enabled:
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw="",
                resolved_text=text,
                error="coreference_resolution disabled",
            )

        prompt = self._build_prompt(text)
        try:
            raw = await self._call_llm_with_retries(prompt)
            items = self._parse_items(raw)
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.observe("coreference_resolution.replacements", float(len(items)))
            resolved_text = self._apply_replacements(text, items)
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw=self._normalize_raw_output(raw),
                resolved_text=resolved_text,
                error=None,
            )
        except Exception as exc:
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.inc("coreference_resolution.exceptions", 1)
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw="",
                resolved_text=text,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def resolve_chunk_text(
        self,
        text: str,
        *,
        context_before: str = "",
        context_after: str = "",
    ) -> DocumentWithCoreferenceResolution:
        if not self.enabled:
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw="",
                resolved_text=text,
                error="coreference_resolution disabled",
            )

        prompt = self._build_chunk_prompt(
            text,
            context_before=context_before,
            context_after=context_after,
        )
        try:
            raw = await self._call_llm_with_retries(prompt)
            items = self._parse_items(raw)
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.observe("coreference_resolution.chunk_replacements", float(len(items)))
            resolved_text = self._apply_replacements(text, items)
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw=self._normalize_raw_output(raw),
                resolved_text=resolved_text,
                error=None,
            )
        except Exception as exc:
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.inc("coreference_resolution.chunk_exceptions", 1)
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw="",
                resolved_text=text,
                error=f"{type(exc).__name__}: {exc}",
            )
