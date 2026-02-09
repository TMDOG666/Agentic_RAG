# Graph Construction Manager Module

import asyncio
from dataclasses import dataclass
from typing import Callable, List, Optional

from .chunker import SemanticChunker
from .coreference_resolver import CoreferenceResolver, DocumentWithCoreferenceResolution
from .entity_relation_extractor import Chunk, ChunkWithEntityRelationRaw, EntityRelationExtractor
from .entity_relation_parser import ParsedEntityRelation, parse_entity_relation_raw


"""grag.graph_construction.graph_construction_manager

图构建流程编排器（Manager / Orchestrator）。

职责：
- 接收外部输入（文档名称、时间、文本内容）
- 串联图构建的前置流水线：
    1) 全文指代消解
    2) 分块
    3) 实体关系抽取
    4) raw 结果解析为结构化对象
    5) 图谱构建（当前留空占位）

设计原则：
- “流程编排”与“具体能力模块”解耦：
  chunking/coref/extract/parse 都在各自模块实现，这里只负责调用顺序与数据组织。
- 便于测试：支持注入 fake LLM chat 函数，避免单测/本地调试时请求真实大模型。
"""


@dataclass(frozen=True)
class GraphConstructionInput:
    """图构建输入结构。"""

    doc_name: str
    doc_time: str
    text: str


@dataclass(frozen=True)
class ChunkExtractionParsed:
    """单个 chunk 的抽取+解析结果。

    - entity_relation_raw: 抽取器返回的原始多行文本
    - parsed: 解析器将 raw 转换为结构化 entity/relation 对象
    - error: 抽取器阶段的错误（解析器错误会体现在 parsed.errors）
    """

    chunk_id: str
    text: str
    entity_relation_raw: str
    parsed: ParsedEntityRelation
    error: Optional[str]


@dataclass(frozen=True)
class GraphConstructionResult:
    """整篇文档的图构建流水线结果。

    - coreference: 全文指代消解结果（含 raw JSON 与 resolved_text）
    - chunks: 分块后每个 chunk 的抽取+解析结果
    - graph: 图谱构建产物（当前留空）
    """

    doc_name: str
    doc_time: str
    original_text: str
    coreference: DocumentWithCoreferenceResolution
    chunks: List[ChunkExtractionParsed]
    graph: Optional[object]


class GraphConstructionManager:
    def __init__(
        self,
        *,
        coref_llm_chat_fn: Optional[Callable[[str], str]] = None,
        entity_relation_llm_chat_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        """创建流程编排器。

        Args:
            coref_llm_chat_fn:
                指代消解阶段使用的 LLM chat 函数。
                - None：使用配置里的 provider，走 `LLMClient(...).chat`
                - 非 None：用于测试/自定义调用

            entity_relation_llm_chat_fn:
                实体关系抽取阶段使用的 LLM chat 函数。
                - None：使用配置里的 provider，走 `LLMClient(...).chat`
                - 非 None：用于测试/自定义调用
        """
        self._coref_llm_chat_fn = coref_llm_chat_fn
        self._entity_relation_llm_chat_fn = entity_relation_llm_chat_fn

    def run(self, text: str, doc_time: str, doc_name: str) -> GraphConstructionResult:
        """执行图构建前置流水线。

        Args:
            text: 文档全文
            doc_time: 文档时间（建议 ISO8601 字符串；此处作为元数据透传）
            doc_name: 文档名称/唯一标识

        Returns:
            GraphConstructionResult: 包含各步骤产物的结构化结果。

        流程：
        1) 全文指代消解（CoreferenceResolver.resolve_text）
        2) 对消解后的全文进行分块（SemanticChunker.chunk）
        3) 对 chunks 做实体关系抽取（EntityRelationExtractor.extract_many）
        4) 对每个 chunk 的 raw 输出做解析（parse_entity_relation_raw）
        5) 图谱构建（占位）
        """

        # Step 1) 全文指代消解
        coref_resolver = CoreferenceResolver(llm_chat_fn=self._coref_llm_chat_fn)
        coref_result = asyncio.run(coref_resolver.resolve_text(text))

        # Step 2) 分块：对“消解后的全文”分块
        chunker = SemanticChunker()
        chunk_texts = chunker.chunk(coref_result.resolved_text)

        chunks: List[Chunk] = []
        for i, t in enumerate(chunk_texts, 1):
            # chunk_id 这里按 doc_name + 序号生成，便于后续溯源。
            chunks.append(Chunk(chunk_id=f"{doc_name}::chunk_{i}", text=t))

        # Step 3) 实体关系抽取（extractor 内部会根据 bench_num 控并发）
        extractor = EntityRelationExtractor(llm_chat_fn=self._entity_relation_llm_chat_fn)
        extracted: List[ChunkWithEntityRelationRaw] = asyncio.run(extractor.extract_many(chunks))

        parsed_chunks: List[ChunkExtractionParsed] = []
        for r in extracted:
            # Step 4) raw 解析为结构化对象
            parsed = parse_entity_relation_raw(r.entity_relation_raw)
            parsed_chunks.append(
                ChunkExtractionParsed(
                    chunk_id=r.chunk_id,
                    text=r.text,
                    entity_relation_raw=r.entity_relation_raw,
                    parsed=parsed,
                    error=r.error,
                )
            )

        # Step 5) 图谱构建（未实现，占位）
        graph_placeholder = None

        return GraphConstructionResult(
            doc_name=doc_name,
            doc_time=doc_time,
            original_text=text,
            coreference=coref_result,
            chunks=parsed_chunks,
            graph=graph_placeholder,
        )