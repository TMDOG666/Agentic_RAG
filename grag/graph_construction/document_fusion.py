from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Optional, Sequence

from grag.monitoring.monitoring_manager import MonitoringManager, use_monitor

from .entity_resolution_knowledge_fusion import (
    IntraDocumentFusionResult,
    collect_entities_from_chunks,
    resolve_and_fuse_intra_document,
)
from .types import ChunkExtractionParsed, GraphConstructionResult, GraphConstructionStreamEvent
from .coreference_resolver import DocumentWithCoreferenceResolution


class DocumentFusionProcessor:
    """负责文档级融合，不再混入 chunk 级抽取流程。"""

    def __init__(
        self,
        *,
        fusion_llm_chat_fn: Optional[Callable[[str], str]] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
    ) -> None:
        self._fusion_llm_chat_fn = fusion_llm_chat_fn
        self._embedding_fn = embedding_fn

    def fuse_document(
        self,
        *,
        parsed_chunks: Sequence[ChunkExtractionParsed],
        text: str,
        doc_name: str,
        doc_time: str,
        group_id: str = "default",
        doc_id: str,
        event_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
    ) -> GraphConstructionResult:
        def emit(
            event_type: str,
            stage: str,
            *,
            message: str,
            total_chunks: Optional[int] = None,
            payload: Optional[Dict[str, object]] = None,
        ) -> None:
            if event_callback is None:
                return
            event_callback(
                GraphConstructionStreamEvent(
                    event_type=event_type,
                    stage=stage,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    group_id=group_id,
                    total_chunks=total_chunks,
                    message=message,
                    payload=payload,
                )
            )

        monitor = MonitoringManager(
            doc_name=doc_name,
            base_attrs={"doc_time": doc_time, "group_id": group_id, "doc_id": doc_id},
        )
        with use_monitor(monitor):
            fusion_result = self._run_fusion(parsed_chunks=parsed_chunks, emit=emit, monitor=monitor)
            result = GraphConstructionResult(
                doc_name=doc_name,
                doc_time=doc_time,
                original_text=text,
                coreference=DocumentWithCoreferenceResolution(
                    text=text,
                    coreference_raw="",
                    resolved_text=text,
                    error="document-level coreference disabled; chunk-local coreference enabled",
                ),
                chunks=list(parsed_chunks),
                graph={"intra_document_fusion": fusion_result},
            )
            emit(
                "document.completed",
                "completed",
                message="graph construction completed",
                total_chunks=len(parsed_chunks),
            )
            monitor.export_json()
            return result

    def _run_fusion(
        self,
        *,
        parsed_chunks: Sequence[ChunkExtractionParsed],
        emit,
        monitor: MonitoringManager,
    ) -> IntraDocumentFusionResult:
        fusion_input_entities = collect_entities_from_chunks(
            (chunk.chunk_id, chunk.parsed.entities) for chunk in parsed_chunks
        )
        fusion_input_relations = [relation for chunk in parsed_chunks for relation in chunk.parsed.relations]
        monitor.observe("fusion.input_entities", float(len(fusion_input_entities)))
        monitor.observe("fusion.input_relations", float(len(fusion_input_relations)))
        emit(
            "document.fusion.started",
            "intra_document_fusion",
            message="intra-document fusion started",
            total_chunks=len(parsed_chunks),
        )
        with monitor.span("intra_document_fusion"):
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

        emit(
            "document.fusion.done",
            "intra_document_fusion",
            message="intra-document fusion completed",
            total_chunks=len(parsed_chunks),
            payload={
                "fused_entities": len(fusion_result.fused_entities),
                "rewritten_relations": len(fusion_result.rewritten_relations),
                "errors": len(fusion_result.errors),
            },
        )
        monitor.record_result(
            "intra_document_fusion",
            {
                "clusters": len(fusion_result.clusters),
                "fused_entities": [entity.canonical_name for entity in fusion_result.fused_entities[:50]],
                "alias_map_size": len(fusion_result.alias_to_canonical),
                "rewritten_relations": [
                    {
                        "s": relation.subject,
                        "o": relation.object,
                        "t": relation.relation_type,
                        "c": relation.confidence,
                    }
                    for relation in fusion_result.rewritten_relations[:50]
                ],
                "errors": fusion_result.errors[:50],
            },
        )
        return fusion_result
