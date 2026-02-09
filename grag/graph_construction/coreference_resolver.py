import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from ..config import get_settings
from ..model.llm_client import LLMClient


"""grag.graph_construction.coreference_resolver

指代消解模块（文档级）。

核心能力：
- 从 `config/grag_config.yaml` 的 `graph_construction.coreference_resolution` 读取配置
- 对整篇文档文本进行一次指代消解（不并发）
- 对单次指代消解失败进行重试（`max_retries` + `base_sleep_seconds` 指数退避）
- 将 LLM 输出的 JSON 列表（row/raw -> result）应用到原文：把原文中与 row 匹配的片段替换为 result

注意：
- 该步骤通常是“图构建流水线”的第一步：先对整篇文档做一次消歧，再对消解后的文本进行分块。
- LLM 调用接口为同步函数 `LLMClient.chat(prompt) -> str`，这里通过 `asyncio.to_thread()` 包装为可并发的 async 任务。
- 为了便于单元测试，本模块支持注入 `llm_chat_fn`，避免测试时真的请求外部 LLM。
"""


COREFERENCE_RESOLUTION_PROMPT = """
**Role (角色):**
你是一名专业的文本编辑和指代消解专家。你的任务是优化给定的文本，将文中模糊的代词或泛指名词，替换为具体的实体名称，以消除歧义。

**Goal (目标):**
阅读输入文本，识别所有指代不清的短语。输出一个 JSON 列表，用于指导程序将原始文本中的模糊短语替换为清晰的实体短语。

**Output Format (输出格式):**
请仅输出一个合法的 JSON 列表，格式如下：
[
  {{
    "raw": "原文中包含代词的短语片段",
    "result": "替换代词后的完整短语片段"
  }},
  ...
]

**Critical Rules (关键原则):**
1.  **唯一性上下文 (Context is King)**:
    *   不要只输出一个单独的“他”或“它”作为 `raw`。程序会进行全局替换，这会导致错误。
    *   **必须**在 `raw` 中包含前后 2-5 个字的上下文，确保该短语在文中是**唯一**或**易于定位**的。
    *   例如：
        *   错误: `{{"raw": "他", "result": "马斯克"}}` (这会替换文中所有的“他”)
        *   正确: `{{"raw": "他推开了门", "result": "马斯克推开了门"}}`
        *   正确: `{{"raw": "交给她一份", "result": "交给苏珊一份"}}`

2.  **准确性 (Accuracy)**:
    *   `result` 必须保留 `raw` 中的上下文文字，仅替换其中的代词部分。
    *   只处理指代不清的地方。如果原文已经很清楚（如“马斯克推开了门”），不要处理。

3.  **完整性 (Completeness)**:
    *   扫描整段文本，按在文中出现的顺序输出所有需要消解的项。

4.  **无多余内容**: 不要输出 Markdown 标记（如 ```json)，不要输出解释性文字，只输出纯 JSON 字符串。

**Example (示例):**

**Input:**
> 警长推开了审讯室的门。他看起来很疲惫。嫌疑人坐在椅子上，低着头。警长把一份文件扔在桌上，问道：“这是你干的吗？”

**Output:**
[
  {{"raw": "他看起来很", "result": "警长看起来很"}},
  {{"raw": "这是你干的", "result": "这是嫌疑人干的"}}
]

***

**待处理文本:**
{text}
"""


@dataclass
class DocumentWithCoreferenceResolution:
    """指代消解后的文档输出结构。

    - coreference_raw: LLM 返回的原始 JSON 字符串（按 prompt 要求应为 list[dict]）
    - resolved_text: 将 coreference_raw 解析并对原文做替换后的全文
    - error: 文档级指代消解错误信息；为 None 表示成功
    """

    text: str
    coreference_raw: str
    resolved_text: str
    error: Optional[str] = None


class CoreferenceResolver:
    def __init__(
        self,
        llm_chat_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        """创建指代消解器。

        Args:
            llm_chat_fn:
                可选的 LLM 调用函数，签名为 (prompt: str) -> str。
                - 传入时：用于测试/自定义调用
                - 不传：默认使用配置里的 `model_provider` 构造 `LLMClient(model_provider).chat`
        """
        settings = get_settings()
        cfg = settings.graph_construction.coreference_resolution

        def _get_value(key: str, default: Any):
            if cfg is None:
                return default
            if isinstance(cfg, dict):
                return cfg.get(key, default)
            return getattr(cfg, key, default)

        self.enabled: bool = bool(_get_value("enabled", True))
        self.model_provider: str = str(_get_value("model_provider", settings.llm_provider))
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
        """将模板渲染为最终 prompt。

        prompt 中约束了：
        - raw 不能是单独的代词，而是要带 2-5 个字上下文，确保可定位
        - 仅输出合法 JSON 列表，不要 markdown 或解释文本
        """
        return COREFERENCE_RESOLUTION_PROMPT.format(text=text)

    async def _call_llm_with_retries(self, prompt: str) -> str:
        """对单次 LLM 调用做重试封装（指数退避 + 少量抖动）。"""
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                return await asyncio.to_thread(self._llm_chat_fn, prompt)
            except Exception as e:
                last_exc = e
                if attempt >= self.max_retries - 1:
                    break
                sleep_s = self.base_sleep_seconds * (2**attempt)
                sleep_s = sleep_s + random.random() * 0.2 * sleep_s
                await asyncio.sleep(sleep_s)
        raise RuntimeError(str(last_exc) if last_exc else "LLM call failed")

    @staticmethod
    def _parse_json_list(raw: str) -> List[dict]:
        """解析 LLM 的 JSON 输出。

        期望格式：
            [
              {"raw": "...", "result": "..."},
              ...
            ]

        兼容处理：
        - 历史/错误 prompt 可能使用 row，这里允许用 row 作为 fallback
        - 忽略非 dict 项、缺字段项
        """
        raw = (raw or "").strip()
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

    @staticmethod
    def _apply_replacements(text: str, items: List[dict]) -> str:
        """按 LLM 结果逐条替换。

        采用“按顺序 replace”的简单策略：
        - 优点：实现简单，且 prompt 已要求 raw 需要足够上下文以避免误替换
        - 风险：如果 raw 在文本中出现多次，`str.replace` 会全部替换（这也是 prompt 强调“raw 必须唯一可定位”的原因）
        """
        resolved = text
        for it in items:
            raw_key = it.get("raw", "")
            result = it.get("result", "")
            if not raw_key:
                continue
            if raw_key in resolved:
                resolved = resolved.replace(raw_key, result)
        return resolved

    async def resolve_text(self, text: str) -> DocumentWithCoreferenceResolution:
        """对整篇文档进行一次指代消解。

        产出：
        - `coreference_raw`：LLM 输出的 JSON 字符串
        - `resolved_text`：应用替换后的全文

        注意：
        - 指代消解失败会回退到原文，避免阻断后续分块与实体关系抽取。
        """
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
            raw = (raw or "").strip()
            items = self._parse_json_list(raw)
            resolved_text = self._apply_replacements(text, items)
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw=raw,
                resolved_text=resolved_text,
                error=None,
            )
        except Exception as e:
            return DocumentWithCoreferenceResolution(
                text=text,
                coreference_raw="",
                resolved_text=text,
                error=f"{type(e).__name__}: {e}",
            )