import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from grag.monitoring.monitoring_manager import get_current_monitor

from ..config import get_config_manager
from ..model.llm_client import LLMClient


ENTITY_RELATION_PROMPT_TEMPLATE = """
**Role (角色):**
你是一位资深的知识图谱构建专家和数据分析师。你的任务是从给定的输入文本中，精准地抽取所有的“实体（Entity）”以及实体之间的“关系（Relation）”。

**Goal (目标):**
请阅读提供的文本，理解其上下文逻辑、因果关系和事实细节，输出两个列表：
1.  **实体列表**：包含文本中提到的关键人名、地名、组织、物品、概念、时间、数值等。
2.  **关系列表**：描述实体之间存在的客观事实、互动、从属或逻辑关联。

**Output Format (输出格式):**
请严格遵守以下格式要求，不要使用 JSON 或 XML，仅使用 `<|SEP|>` 作为分隔符。
处理完成后，必须在最后一行输出一个明确的结束信号，如 `<|DONE|>`

**1. 实体行格式:**
`entity<|SEP|>实体名称<|SEP|>类型<|SEP|>描述`
*   **实体名称**: 文本中的原名或标准名称。
*   **类型**: 如：人物、地点、组织、公司、物品、时间、数值、概念、事件等。
*   **描述**: 基于文本内容，简要概括该实体的属性或身份（20字以内）。
*   **用户自定义实体类型**: {user_entity_types}

**2. 关系行格式:**
`relation<|SEP|>主体<|SEP|>客体<|SEP|>关系描述<|SEP|>关系类型<|SEP|>置信度`
*   **主体/客体**: 必须完全匹配“实体列表”中的名称。
*   **关系描述**: 用一句通顺的话描述两者的关系（如“A是B的创始人”或“A击败了B”）。
*   **关系类型**: 简短的标签，如：隶属、位于、雇佣、发布、敌对、亲属、财务_收入等。
*   **关系强度**: 评估关系在文中的**直接性和重要性**，给予 1-10 的整数评分。10代表最直接、最重要的关系（如创始人与公司的关系）；1代表最弱、最间接的关联。

**Rules (原则):**
1.  **全面性**: 不要遗漏关键信息，包括数值对应的归属、隐含的人物关系等。
2.  **准确性**: 区分“前任”与“现任”，区分“计划中”与“已发生”。
3.  **独立性**: 如果一个实体有多个称呼（如“他”、“国王”），请统一解析为最具体的名称（如“亚瑟王”），并在描述中体现。
4.  **去重**: 同一个实体只列出一次；同一对关系只列出一次。

***

**Examples (示例):**

**输入文本 1 (商业/科技类):**
> 2023年9月，星云动力（Nebula Dynamics）在旧金山发布了新一代外骨骼机器人“泰坦X”。首席执行官艾伦·斯塔克在发布会上宣布，泰坦X的售价为4.5万美元，并将首批交付给太平洋矿业集团用于深井作业。虽然面临供应链短缺，但公司本季度营收依然达到了1.2亿美元。

**输出 1:**
```text
entity<|SEP|>星云动力<|SEP|>公司<|SEP|>一家位于旧金山的科技公司，发布了外骨骼机器人。
entity<|SEP|>2023年9月<|SEP|>时间<|SEP|>产品发布的时间点。
entity<|SEP|>旧金山<|SEP|>地点<|SEP|>星云动力的发布会举办地及可能所在地。
entity<|SEP|>泰坦X<|SEP|>产品<|SEP|>星云动力发布的新一代外骨骼机器人。
entity<|SEP|>艾伦·斯塔克<|SEP|>人物<|SEP|>星云动力的首席执行官。
entity<|SEP|>4.5万美元<|SEP|>数值<|SEP|>泰坦X的单台售价。
entity<|SEP|>太平洋矿业集团<|SEP|>公司<|SEP|>泰坦X的首批客户。
entity<|SEP|>1.2亿美元<|SEP|>数值<|SEP|>星云动力本季度的营收额。
relation<|SEP|>星云动力<|SEP|>泰坦X<|SEP|>星云动力研发并发布了泰坦X机器人。<|SEP|>产品_发布<|SEP|>10
relation<|SEP|>星云动力<|SEP|>旧金山<|SEP|>星云动力在旧金山举办了发布会。<|SEP|>位于/举办地<|SEP|>9
relation<|SEP|>艾伦·斯塔克<|SEP|>星云动力<|SEP|>艾伦·斯塔克是星云动力的CEO。<|SEP|>人事_任职<|SEP|>10
relation<|SEP|>泰坦X<|SEP|>4.5万美元<|SEP|>泰坦X的售价定为4.5万美元。<|SEP|>商业_定价<|SEP|>10
relation<|SEP|>太平洋矿业集团<|SEP|>泰坦X<|SEP|>太平洋矿业集团采购了首批泰坦X。<|SEP|>商业_采购<|SEP|>9
relation<|SEP|>星云动力<|SEP|>1.2亿美元<|SEP|>星云动力本季度实现营收1.2亿美元。<|SEP|>财务_营收<|SEP|>10
<|DONE|>
```

**输入文本 2 (叙事/历史类):**
> 苍蓝历450年，北境守护者加勒特公爵在绝冬城被刺杀。凶手是来自“影刃”组织的刺客，这次行动由帝国宰相维克多秘密策划，意在挑起南北战争以巩固皇权。加勒特的佩剑“霜语”在混乱中遗失，据说被流浪骑士兰斯带往了南方。

**输出 2:**
```text
entity<|SEP|>加勒特公爵<|SEP|>人物<|SEP|>北境守护者，在绝冬城被刺杀。
entity<|SEP|>苍蓝历450年<|SEP|>时间<|SEP|>事件发生的时间。
entity<|SEP|>绝冬城<|SEP|>地点<|SEP|>加勒特公爵遇刺的地点。
entity<|SEP|>影刃<|SEP|>组织<|SEP|>执行刺杀行动的刺客组织。
entity<|SEP|>维克多<|SEP|>人物<|SEP|>帝国宰相，刺杀行动的幕后策划者。
entity<|SEP|>霜语<|SEP|>物品<|SEP|>加勒特公爵的佩剑，在事件中遗失。
entity<|SEP|>兰斯<|SEP|>人物<|SEP|>流浪骑士，据传带走了“霜语”。
entity<|SEP|>南北战争<|SEP|>事件<|SEP|>维克多策划刺杀意图引发的战争。
relation<|SEP|>加勒特公爵<|SEP|>绝冬城<|SEP|>加勒特公爵在绝冬城驻守并遇害。<|SEP|>位于/遇害地<|SEP|>10
relation<|SEP|>影刃<|SEP|>加勒特公爵<|SEP|>影刃组织的成员刺杀了加勒特公爵。<|SEP|>敌对_刺杀<|SEP|>10
relation<|SEP|>维克多<|SEP|>影刃<|SEP|>维克多策划并指使影刃执行行动。<|SEP|>策划/指使<|SEP|>9
relation<|SEP|>维克多<|SEP|>加勒特公爵<|SEP|>维克多策划了针对加勒特的刺杀。<|SEP|>敌对_谋杀<|SEP|>10
relation<|SEP|>加勒特公爵<|SEP|>霜语<|SEP|>霜语是加勒特公爵的佩剑。<|SEP|>持有<|SEP|>10
relation<|SEP|>兰斯<|SEP|>霜语<|SEP|>兰斯带走了遗失的霜语剑。<|SEP|>持有/带走<|SEP|>8
relation<|SEP|>维克多<|SEP|>南北战争<|SEP|>维克多意图通过刺杀挑起南北战争。<|SEP|>引发/动机<|SEP|>9
<|DONE|>
```

***

**Input Text (待抽取文本):**
{text}
"""


"""grag.graph_construction.entity_relation_extractor

实体关系抽取模块（并发版）。

核心能力：
- 从 `config/grag_config.yaml` 的 `graph_construction.entity_relation_extraction` 读取配置
- 对输入 `List[Chunk]` 进行异步并发抽取（`bench_num` 控制并发数）
- 对单个 chunk 抽取失败进行重试（`max_retries` + `base_sleep_seconds` 指数退避）

注意：
- 目前 LLM 的调用接口为同步函数 `LLMClient.chat(prompt) -> str`
  因此这里通过 `asyncio.to_thread()` 把同步调用包装为可并发的 async 任务。
- 为了便于单元测试，本类支持注入 `llm_chat_fn`，避免测试时真的请求外部 LLM。
"""


@dataclass(frozen=True)
class Chunk:
    """分块后的最小输入结构。

    chunk_id 由上层构造（例如 chunk_{顺序}_{uuid}）。
    """
    chunk_id: str
    text: str


@dataclass
class ChunkWithEntityRelationRaw:
    """抽取后的 chunk 输出结构。

    - entity_relation_raw: LLM 返回的原始文本（包含 entity/relation 行）
    - error: 本 chunk 的错误信息；为 None 表示成功
    """
    chunk_id: str
    text: str
    entity_relation_raw: str
    error: Optional[str] = None


class EntityRelationExtractor:
    def __init__(
        self,
        llm_chat_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        """创建抽取器。

        Args:
            llm_chat_fn:
                可选的 LLM 调用函数，签名为 (prompt: str) -> str。
                - 传入时：用于测试/自定义调用
                - 不传：默认使用配置里的 `model_provider` 构造 `LLMClient(model_provider).chat`
        """
        settings = get_config_manager().get_settings()
        cfg = settings.graph_construction.entity_relation_extraction

        def _get_value(key: str, default: Any):
            if cfg is None:
                return default
            if isinstance(cfg, dict):
                return cfg.get(key, default)
            return getattr(cfg, key, default)

        self.enabled: bool = bool(_get_value("enabled", True))
        self.model_provider: str = str(_get_value("model_provider", settings.llm_provider))
        self.confidence_threshold: float = float(_get_value("confidence_threshold", 0.7))
        self.max_entities_per_chunk: int = int(_get_value("max_entities_per_chunk", 10))
        self.bench_num: int = int(_get_value("bench_num", 4))
        self.user_entity_type: List[str] = list(_get_value("user_entity_type", []))
        self.max_retries: int = int(_get_value("max_retries", 3))
        self.base_sleep_seconds: float = float(_get_value("base_sleep_seconds", 2.0))

        if self.bench_num <= 0:
            raise ValueError("bench_num must be > 0")
        if self.max_retries <= 0:
            raise ValueError("max_retries must be > 0")
        if self.base_sleep_seconds <= 0:
            raise ValueError("base_sleep_seconds must be > 0")

        if llm_chat_fn is not None:
            self._llm_chat_fn = llm_chat_fn
        else:
            self._llm_chat_fn = LLMClient(self.model_provider).chat

        self._semaphore = asyncio.Semaphore(self.bench_num)

    def _build_prompt(self, text: str) -> str:
        """根据配置把 prompt 模板渲染为最终提示词。"""
        user_types_str = ", ".join(self.user_entity_type) if self.user_entity_type else "[]"
        return ENTITY_RELATION_PROMPT_TEMPLATE.format(
            user_entity_types=user_types_str,
            text=text,
        )

    async def _call_llm_with_retries(self, prompt: str) -> str:
        """对单次 LLM 调用做重试封装（指数退避 + 少量抖动）。"""
        monitor = get_current_monitor()
        if monitor is not None:
            monitor.inc("entity_relation_extraction.llm_calls", 1)
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                if monitor is not None:
                    monitor.inc("entity_relation_extraction.llm_attempts", 1)
                with (
                    monitor.span("entity_relation_extraction.llm_call")
                    if monitor is not None
                    else self._null_span()
                ):
                    return await asyncio.to_thread(self._llm_chat_fn, prompt)
            except Exception as e:
                last_exc = e
                if monitor is not None:
                    monitor.inc("entity_relation_extraction.llm_errors", 1)
                if attempt >= self.max_retries - 1:
                    break
                if monitor is not None:
                    monitor.inc("entity_relation_extraction.llm_retries", 1)
                sleep_s = self.base_sleep_seconds * (2**attempt)
                sleep_s = sleep_s + random.random() * 0.2 * sleep_s
                await asyncio.sleep(sleep_s)
        raise RuntimeError(str(last_exc) if last_exc else "LLM call failed")

    @staticmethod
    def _null_span():
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()

    async def extract_one(self, chunk: Chunk) -> ChunkWithEntityRelationRaw:
        """抽取单个 chunk（并发受 semaphore 控制）。"""
        if not self.enabled:
            monitor = get_current_monitor()
            if monitor is not None:
                monitor.inc("entity_relation_extraction.disabled", 1)
            return ChunkWithEntityRelationRaw(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                entity_relation_raw="",
                error="entity_relation_extraction disabled",
            )

        async with self._semaphore:
            prompt = self._build_prompt(chunk.text)
            try:
                raw = await self._call_llm_with_retries(prompt)
                raw = (raw or "").strip()
                monitor = get_current_monitor()
                if monitor is not None:
                    monitor.inc("entity_relation_extraction.chunk_success", 1)
                    monitor.observe("entity_relation_extraction.raw_chars", float(len(raw)))
                return ChunkWithEntityRelationRaw(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    entity_relation_raw=raw,
                    error=None,
                )
            except Exception as e:
                monitor = get_current_monitor()
                if monitor is not None:
                    monitor.inc("entity_relation_extraction.chunk_failed", 1)
                return ChunkWithEntityRelationRaw(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    entity_relation_raw="",
                    error=f"{type(e).__name__}: {e}",
                )

    async def extract_many(self, chunks: List[Chunk]) -> List[ChunkWithEntityRelationRaw]:
        """并发抽取多个 chunks。

        返回列表顺序与输入 chunks 顺序一致。
        """
        tasks = [asyncio.create_task(self.extract_one(ch)) for ch in chunks]
        return await asyncio.gather(*tasks)