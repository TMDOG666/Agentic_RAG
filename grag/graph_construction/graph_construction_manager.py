# Graph Construction Manager Module

import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

from grag.monitoring.monitoring_manager import MonitoringManager, use_monitor

from .chunker import SemanticChunker
from .coreference_resolver import CoreferenceResolver, DocumentWithCoreferenceResolution
from .entity_relation_extractor import Chunk, ChunkWithEntityRelationRaw, EntityRelationExtractor
from .entity_relation_parser import ParsedEntityRelation, parse_entity_relation_raw

from .entity_resolution_knowledge_fusion import (
    IntraDocumentFusionResult,
    collect_entities_from_chunks,
    resolve_and_fuse_intra_document,
)


"""grag.graph_construction.graph_construction_manager

图构建流程编排器（Manager / Orchestrator）。

职责：
- 仅负责“流程编排”（Orchestration）：
  - 指代消解 coreference
  - 分块 chunking
  - 实体/关系抽取 extraction
  - 抽取结果解析 parsing
  - 文档内实体融合与关系重写 fusion

非职责（不在本模块实现）：
- 构建“可入库资产”（Document/Chunk/Embedding/Entity/Relation 的存储数据结构）
- 计算 chunk embedding
- 调用 storage/数据库进行落库

这些与“持久化/资产构建”相关的逻辑，应由 `grag.graph_construction.graph_builder.GraphBuilder` 承担。

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
        fusion_llm_chat_fn: Optional[Callable[[str], str]] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
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
        self._fusion_llm_chat_fn = fusion_llm_chat_fn
        self._embedding_fn = embedding_fn

    def run(
        self,
        text: str,
        doc_time: str,
        doc_name: str,
        *,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphConstructionResult:
        """执行图构建前置流水线。

        Args:
            text: 文档全文
            doc_time: 文档时间（建议 ISO8601 字符串；此处作为元数据透传）
            doc_name: 文档名称/唯一标识
        """

        # doc_id 用于幂等、隔离与可追踪：
        # - GraphConstructionManager 会在 chunk_id 中引用它
        # - GraphBuilder 会使用它来构建落库主键/唯一键
        if doc_id is None:
            doc_id = uuid.uuid4().hex

        monitor = MonitoringManager(
            doc_name=doc_name,
            base_attrs={"doc_time": doc_time, "group_id": group_id, "doc_id": doc_id},
        )

        with use_monitor(monitor):
            monitor.inc("graph_construction.run", 1)

            with monitor.span("coreference_resolution"):
                # 1) 全文指代消解：减少代词/省略带来的歧义，提升后续抽取质量
                coref_resolver = CoreferenceResolver(llm_chat_fn=self._coref_llm_chat_fn)
                coref_result = asyncio.run(coref_resolver.resolve_text(text))
                if coref_result.error:
                    monitor.inc("coreference_resolution.errors", 1)

            monitor.record_result(
                "coreference_resolution",
                {
                    "error": coref_result.error,
                    "coreference_raw_chars": len(coref_result.coreference_raw or ""),
                    "resolved_text_preview": (coref_result.resolved_text or "")[:500],
                },
            )

            with monitor.span("chunking"):
                # 2) 分块：将长文拆成适合 LLM 的 chunk
                chunker = SemanticChunker()
                chunk_texts = chunker.chunk(coref_result.resolved_text)
                monitor.observe("chunking.chunks", float(len(chunk_texts)))

            monitor.record_result(
                "chunking",
                {
                    "chunks": len(chunk_texts),
                    "chunk_chars": [len(t) for t in chunk_texts[:50]],
                    "first_chunk_preview": (chunk_texts[0] if chunk_texts else "")[:500],
                },
            )

            chunks: List[Chunk] = []
            for i, t in enumerate(chunk_texts, 1):
                # chunk_id 采用“doc_id::chunk_{i}”的稳定格式：
                # - 有利于下游 embedding / 入库时做幂等
                # - 同一 doc_id 下 chunk 序号稳定可复现
                chunks.append(Chunk(chunk_id=f"{doc_id}::chunk_{i}", text=t))

            with monitor.span("entity_relation_extraction", chunks=len(chunks)):
                # 3) 实体/关系抽取：逐 chunk 调 LLM 产出 raw 文本
                extractor = EntityRelationExtractor(llm_chat_fn=self._entity_relation_llm_chat_fn)
                extracted: List[ChunkWithEntityRelationRaw] = asyncio.run(extractor.extract_many(chunks))
                monitor.observe("entity_relation_extraction.results", float(len(extracted)))

                monitor.observe(
                    "entity_relation_extraction.chunk_errors",
                    float(sum(1 for r in extracted if r.error)),
                )

            monitor.record_result(
                "entity_relation_extraction",
                {
                    "chunks": len(extracted),
                    "chunk_errors": sum(1 for r in extracted if r.error),
                    "samples": [
                        {
                            "chunk_id": r.chunk_id,
                            "error": r.error,
                            "raw_preview": (r.entity_relation_raw or "")[:500],
                        }
                        for r in extracted[:10]
                    ],
                },
            )

            parsed_chunks: List[ChunkExtractionParsed] = []
            with monitor.span("entity_relation_parsing"):
                # 4) 解析 raw 抽取文本为结构化实体/关系对象
                for r in extracted:
                    parsed = parse_entity_relation_raw(r.entity_relation_raw)
                    monitor.observe("entity_relation_parsing.entities", float(len(parsed.entities)))
                    monitor.observe("entity_relation_parsing.relations", float(len(parsed.relations)))
                    monitor.observe("entity_relation_parsing.parse_errors", float(len(parsed.errors)))

                    parsed_chunks.append(
                        ChunkExtractionParsed(
                            chunk_id=r.chunk_id,
                            text=r.text,
                            entity_relation_raw=r.entity_relation_raw,
                            parsed=parsed,
                            error=r.error,
                        )
                    )

            monitor.record_result(
                "entity_relation_parsing",
                {
                    "chunks": len(parsed_chunks),
                    "total_entities": sum(len(c.parsed.entities) for c in parsed_chunks),
                    "total_relations": sum(len(c.parsed.relations) for c in parsed_chunks),
                    "total_parse_errors": sum(len(c.parsed.errors) for c in parsed_chunks),
                    "samples": [
                        {
                            "chunk_id": c.chunk_id,
                            "entities": [e.name for e in c.parsed.entities[:20]],
                            "relations": [
                                {
                                    "s": r.subject,
                                    "o": r.object,
                                    "t": r.relation_type,
                                    "c": r.confidence,
                                }
                                for r in c.parsed.relations[:20]
                            ],
                            "errors": c.parsed.errors[:20],
                        }
                        for c in parsed_chunks[:5]
                    ],
                },
            )

            fusion_input_entities = collect_entities_from_chunks(
                (c.chunk_id, c.parsed.entities) for c in parsed_chunks
            )
            fusion_input_relations = [rel for c in parsed_chunks for rel in c.parsed.relations]
            monitor.observe("fusion.input_entities", float(len(fusion_input_entities)))
            monitor.observe("fusion.input_relations", float(len(fusion_input_relations)))

            with monitor.span("intra_document_fusion"):
                # 5) 文档内融合：
                # - 对多 chunk 抽取出的“同名/近义实体”做聚类与统一
                # - 并将 relations 重写为 canonical entity
                fusion_result: IntraDocumentFusionResult = asyncio.run(
                    resolve_and_fuse_intra_document(
                        entities=fusion_input_entities,
                        relations=fusion_input_relations,
                        llm_chat_fn=self._fusion_llm_chat_fn,
                        embedding_fn=self._embedding_fn,
                    )
                )

                monitor.observe("fusion.fused_entities", float(len(fusion_result.fused_entities)))
                monitor.observe("fusion.rewritten_relations", float(len(fusion_result.rewritten_relations)))
                monitor.observe("fusion.errors", float(len(fusion_result.errors)))

            monitor.record_result(
                "intra_document_fusion",
                {
                    "clusters": len(fusion_result.clusters),
                    "fused_entities": [fe.canonical_name for fe in fusion_result.fused_entities[:50]],
                    "alias_map_size": len(fusion_result.alias_to_canonical),
                    "rewritten_relations": [
                        {
                            "s": r.subject,
                            "o": r.object,
                            "t": r.relation_type,
                            "c": r.confidence,
                        }
                        for r in fusion_result.rewritten_relations[:50]
                    ],
                    "errors": fusion_result.errors[:50],
                },
            )

            graph_placeholder = {
                "intra_document_fusion": fusion_result,
            }

            result = GraphConstructionResult(
                doc_name=doc_name,
                doc_time=doc_time,
                original_text=text,
                coreference=coref_result,
                chunks=parsed_chunks,
                graph=graph_placeholder,
            )

            monitor.export_json()
            return result