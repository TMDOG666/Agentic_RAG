from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from grag.monitoring.monitoring_manager import MonitoringManager, use_monitor

from .chunker import SemanticChunker
from .coreference_resolver import CoreferenceResolver, DocumentWithCoreferenceResolution
from .entity_relation_extractor import Chunk, EntityRelationExtractor
from .entity_relation_parser import ParsedEntityRelation, parse_entity_relation_raw
from .entity_resolution_knowledge_fusion import (
    IntraDocumentFusionResult,
    collect_entities_from_chunks,
    resolve_and_fuse_intra_document,
)


@dataclass(frozen=True)
class GraphConstructionInput:
    doc_name: str
    doc_time: str
    text: str


@dataclass(frozen=True)
class ChunkExtractionParsed:
    chunk_id: str
    text: str
    resolved_text: str
    entity_relation_raw: str
    parsed: ParsedEntityRelation
    error: Optional[str]


@dataclass(frozen=True)
class GraphConstructionResult:
    doc_name: str
    doc_time: str
    original_text: str
    coreference: DocumentWithCoreferenceResolution
    chunks: List[ChunkExtractionParsed]
    graph: Optional[object]


@dataclass(frozen=True)
class GraphConstructionStreamEvent:
    event_type: str
    stage: str
    doc_id: str
    doc_name: str
    group_id: str
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None
    message: str = ""
    payload: Optional[Dict[str, object]] = None


class GraphConstructionManager:
    def __init__(
        self,
        *,
        coref_llm_chat_fn: Optional[Callable[[str], str]] = None,
        entity_relation_llm_chat_fn: Optional[Callable[[str], str]] = None,
        fusion_llm_chat_fn: Optional[Callable[[str], str]] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
    ) -> None:
        self._coref_llm_chat_fn = coref_llm_chat_fn
        self._entity_relation_llm_chat_fn = entity_relation_llm_chat_fn
        self._fusion_llm_chat_fn = fusion_llm_chat_fn
        self._embedding_fn = embedding_fn

    def process_single_chunk(
        self,
        *,
        chunk_texts: Sequence[str],
        chunk_index: int,
        doc_name: str,
        doc_time: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
        event_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
    ) -> ChunkExtractionParsed:
        if doc_id is None:
            doc_id = uuid.uuid4().hex
        if chunk_index < 0 or chunk_index >= len(chunk_texts):
            raise IndexError(f"chunk_index out of range: {chunk_index}")

        chunk = Chunk(chunk_id=f"{doc_id}::chunk_{chunk_index + 1}", text=str(chunk_texts[chunk_index] or ""))
        total_chunks = len(chunk_texts)

        def emit(
            event_type: str,
            stage: str,
            *,
            message: str,
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
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk_index,
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
            coref_resolver = CoreferenceResolver(llm_chat_fn=self._coref_llm_chat_fn)
            extractor = EntityRelationExtractor(llm_chat_fn=self._entity_relation_llm_chat_fn)

            context_before = chunk_texts[chunk_index - 1][-200:] if chunk_index > 0 else ""
            context_after = chunk_texts[chunk_index + 1][:200] if chunk_index + 1 < total_chunks else ""

            emit("chunk.started", "chunk_processing", message=f"processing chunk {chunk_index + 1}/{total_chunks}")

            with monitor.span("chunk_coreference_resolution", chunk_id=chunk.chunk_id):
                chunk_coref = asyncio.run(
                    coref_resolver.resolve_chunk_text(
                        chunk.text,
                        context_before=context_before,
                        context_after=context_after,
                    )
                )

            emit(
                "chunk.coref.done",
                "chunk_coreference",
                message=f"chunk {chunk_index + 1}/{total_chunks} coreference resolved",
                payload={
                    "error": chunk_coref.error,
                    "resolved_chars": len(chunk_coref.resolved_text or ""),
                },
            )

            with monitor.span("entity_relation_extraction", chunk_id=chunk.chunk_id):
                extracted = asyncio.run(
                    extractor.extract_one(
                        Chunk(
                            chunk_id=chunk.chunk_id,
                            text=chunk_coref.resolved_text,
                        )
                    )
                )

            emit(
                "chunk.extract.done",
                "entity_relation_extraction",
                message=f"chunk {chunk_index + 1}/{total_chunks} entity relation extracted",
                payload={"error": extracted.error},
            )

            with monitor.span("entity_relation_parsing", chunk_id=chunk.chunk_id):
                parsed = parse_entity_relation_raw(extracted.entity_relation_raw)
                parse_errors = list(parsed.errors)
                if chunk_coref.error:
                    parse_errors.append(f"coreference warning: {chunk_coref.error}")
                parsed = ParsedEntityRelation(
                    entities=parsed.entities,
                    relations=parsed.relations,
                    errors=parse_errors,
                )

            parsed_chunk = ChunkExtractionParsed(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                resolved_text=chunk_coref.resolved_text,
                entity_relation_raw=extracted.entity_relation_raw,
                parsed=parsed,
                error=extracted.error,
            )

            emit(
                "chunk.parsed.done",
                "entity_relation_parsing",
                message=f"chunk {chunk_index + 1}/{total_chunks} parsed",
                payload={
                    "chunk_text": chunk.text,
                    "resolved_chunk_text": chunk_coref.resolved_text,
                    "coreference_warning": chunk_coref.error or "",
                    "extraction_error": extracted.error or "",
                    "entities": len(parsed.entities),
                    "relations": len(parsed.relations),
                    "parse_errors": len(parsed.errors),
                },
            )
            monitor.export_json()
            return parsed_chunk

    def run(
        self,
        text: str,
        doc_time: str,
        doc_name: str,
        *,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphConstructionResult:
        return self.run_stream(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
            event_callback=None,
        )

    def run_stream(
        self,
        text: str,
        doc_time: str,
        doc_name: str,
        *,
        group_id: str = "default",
        doc_id: Optional[str] = None,
        event_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
        existing_chunks: Optional[Sequence[ChunkExtractionParsed]] = None,
        chunk_texts: Optional[Sequence[str]] = None,
        chunk_result_callback: Optional[
            Callable[[Chunk, int, int, str, Optional[ChunkExtractionParsed], str], None]
        ] = None,
    ) -> GraphConstructionResult:
        if doc_id is None:
            doc_id = uuid.uuid4().hex

        def emit(
            event_type: str,
            stage: str,
            *,
            message: str,
            chunk_id: Optional[str] = None,
            chunk_index: Optional[int] = None,
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
                    chunk_id=chunk_id,
                    chunk_index=chunk_index,
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
            monitor.inc("graph_construction.run", 1)

            with monitor.span("chunking"):
                final_chunk_texts = list(chunk_texts or [])
                if not final_chunk_texts:
                    final_chunk_texts = SemanticChunker().chunk(text)
                monitor.observe("chunking.chunks", float(len(final_chunk_texts)))

            monitor.record_result(
                "chunking",
                {
                    "chunks": len(final_chunk_texts),
                    "chunk_chars": [len(t) for t in final_chunk_texts[:50]],
                    "first_chunk_preview": (final_chunk_texts[0] if final_chunk_texts else "")[:500],
                },
            )
            emit(
                "document.chunked",
                "chunking",
                message=f"document chunked into {len(final_chunk_texts)} chunks",
                total_chunks=len(final_chunk_texts),
                payload={"chunks": len(final_chunk_texts)},
            )

            chunks = [
                Chunk(chunk_id=f"{doc_id}::chunk_{i}", text=chunk_text)
                for i, chunk_text in enumerate(final_chunk_texts, 1)
            ]
            existing_chunk_map = {
                chunk.chunk_id: chunk
                for chunk in (existing_chunks or [])
            }
            parsed_chunks: List[ChunkExtractionParsed] = []
            extraction_samples: List[Dict[str, object]] = []
            parsing_samples: List[Dict[str, object]] = []

            coref_resolver = CoreferenceResolver(llm_chat_fn=self._coref_llm_chat_fn)
            extractor = EntityRelationExtractor(llm_chat_fn=self._entity_relation_llm_chat_fn)

            for i, chunk in enumerate(chunks, 1):
                total_chunks = len(chunks)
                chunk_index = i - 1

                cached_chunk = existing_chunk_map.get(chunk.chunk_id)
                if cached_chunk is not None:
                    parsed_chunks.append(cached_chunk)
                    emit(
                        "chunk.restored",
                        "chunk_resume",
                        message=f"restored chunk {i}/{total_chunks} from checkpoint",
                        chunk_id=chunk.chunk_id,
                        chunk_index=chunk_index,
                        total_chunks=total_chunks,
                        payload={
                            "entities": len(cached_chunk.parsed.entities),
                            "relations": len(cached_chunk.parsed.relations),
                            "parse_errors": len(cached_chunk.parsed.errors),
                        },
                    )
                    continue

                context_before = final_chunk_texts[chunk_index - 1][-200:] if chunk_index > 0 else ""
                context_after = final_chunk_texts[chunk_index + 1][:200] if chunk_index + 1 < total_chunks else ""

                if chunk_result_callback is not None:
                    chunk_result_callback(chunk, chunk_index, total_chunks, "processing", None, "")

                emit(
                    "chunk.started",
                    "chunk_processing",
                    message=f"processing chunk {i}/{total_chunks}",
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                )

                with monitor.span("chunk_coreference_resolution", chunk_id=chunk.chunk_id):
                    chunk_coref = asyncio.run(
                        coref_resolver.resolve_chunk_text(
                            chunk.text,
                            context_before=context_before,
                            context_after=context_after,
                        )
                    )
                    if chunk_coref.error:
                        monitor.inc("coreference_resolution.errors", 1)

                emit(
                    "chunk.coref.done",
                    "chunk_coreference",
                    message=f"chunk {i}/{total_chunks} coreference resolved",
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    payload={
                        "error": chunk_coref.error,
                        "resolved_chars": len(chunk_coref.resolved_text or ""),
                    },
                )

                with monitor.span("entity_relation_extraction", chunk_id=chunk.chunk_id):
                    extracted = asyncio.run(
                        extractor.extract_one(
                            Chunk(
                                chunk_id=chunk.chunk_id,
                                text=chunk_coref.resolved_text,
                            )
                        )
                    )
                    monitor.observe("entity_relation_extraction.results", 1.0)
                    if extracted.error:
                        monitor.observe("entity_relation_extraction.chunk_errors", 1.0)

                extraction_samples.append(
                    {
                        "chunk_id": extracted.chunk_id,
                        "error": extracted.error,
                        "raw_preview": (extracted.entity_relation_raw or "")[:500],
                    }
                )
                emit(
                    "chunk.extract.done",
                    "entity_relation_extraction",
                    message=f"chunk {i}/{total_chunks} entity relation extracted",
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    payload={"error": extracted.error},
                )

                with monitor.span("entity_relation_parsing", chunk_id=chunk.chunk_id):
                    parsed = parse_entity_relation_raw(extracted.entity_relation_raw)
                    parse_errors = list(parsed.errors)
                    if chunk_coref.error:
                        parse_errors.append(f"coreference warning: {chunk_coref.error}")
                    parsed = ParsedEntityRelation(
                        entities=parsed.entities,
                        relations=parsed.relations,
                        errors=parse_errors,
                    )
                    monitor.observe("entity_relation_parsing.entities", float(len(parsed.entities)))
                    monitor.observe("entity_relation_parsing.relations", float(len(parsed.relations)))
                    monitor.observe("entity_relation_parsing.parse_errors", float(len(parsed.errors)))

                parsing_samples.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "entities": [e.name for e in parsed.entities[:20]],
                        "relations": [
                            {
                                "s": r.subject,
                                "o": r.object,
                                "t": r.relation_type,
                                "c": r.confidence,
                            }
                            for r in parsed.relations[:20]
                        ],
                        "errors": parsed.errors[:20],
                    }
                )

                parsed_chunk = ChunkExtractionParsed(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    resolved_text=chunk_coref.resolved_text,
                    entity_relation_raw=extracted.entity_relation_raw,
                    parsed=parsed,
                    error=extracted.error,
                )
                parsed_chunks.append(parsed_chunk)

                if chunk_result_callback is not None:
                    chunk_result_callback(
                        chunk,
                        chunk_index,
                        total_chunks,
                        "failed" if parsed_chunk.error else "completed",
                        parsed_chunk,
                        parsed_chunk.error or "",
                    )

                emit(
                    "chunk.parsed.done",
                    "entity_relation_parsing",
                    message=f"chunk {i}/{total_chunks} parsed",
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    payload={
                        "chunk_text": chunk.text,
                        "resolved_chunk_text": chunk_coref.resolved_text,
                        "coreference_warning": chunk_coref.error or "",
                        "extraction_error": extracted.error or "",
                        "entities": len(parsed.entities),
                        "relations": len(parsed.relations),
                        "parse_errors": len(parsed.errors),
                    },
                )

            monitor.record_result(
                "coreference_resolution",
                {
                    "mode": "chunk_local_only",
                    "chunks": len(parsed_chunks),
                    "chunk_errors": sum(1 for chunk in parsed_chunks if chunk.error),
                    "samples": [
                        {
                            "chunk_id": chunk.chunk_id,
                            "error": chunk.error,
                            "resolved_text_preview": (chunk.resolved_text or "")[:500],
                        }
                        for chunk in parsed_chunks[:10]
                    ],
                },
            )
            monitor.record_result(
                "entity_relation_extraction",
                {
                    "chunks": len(parsed_chunks),
                    "chunk_errors": sum(1 for chunk in parsed_chunks if chunk.error),
                    "samples": extraction_samples[:10],
                },
            )
            monitor.record_result(
                "entity_relation_parsing",
                {
                    "chunks": len(parsed_chunks),
                    "total_entities": sum(len(chunk.parsed.entities) for chunk in parsed_chunks),
                    "total_relations": sum(len(chunk.parsed.relations) for chunk in parsed_chunks),
                    "total_parse_errors": sum(len(chunk.parsed.errors) for chunk in parsed_chunks),
                    "samples": parsing_samples[:5],
                },
            )

            fusion_input_entities = collect_entities_from_chunks(
                (chunk.chunk_id, chunk.parsed.entities)
                for chunk in parsed_chunks
            )
            fusion_input_relations = [rel for chunk in parsed_chunks for rel in chunk.parsed.relations]
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
                chunks=parsed_chunks,
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
