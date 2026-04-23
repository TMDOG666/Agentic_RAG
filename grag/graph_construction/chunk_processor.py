from __future__ import annotations

import asyncio
import uuid
from typing import Callable, Dict, List, Optional, Sequence

from grag.monitoring.monitoring_manager import MonitoringManager, use_monitor

from .coreference_resolver import CoreferenceResolver
from .entity_relation_extractor import Chunk, EntityRelationExtractor
from .entity_relation_parser import ParsedEntityRelation, parse_entity_relation_raw
from .types import ChunkExtractionParsed, GraphConstructionStreamEvent


class GraphChunkProcessor:
    """负责 chunk 级处理：局部指代消解、抽取与解析。"""

    def __init__(
        self,
        *,
        coref_llm_chat_fn: Optional[Callable[[str], str]] = None,
        entity_relation_llm_chat_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._coref_llm_chat_fn = coref_llm_chat_fn
        self._entity_relation_llm_chat_fn = entity_relation_llm_chat_fn

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
            parsed_chunk = self._run_chunk_pipeline(
                chunk=chunk,
                chunk_texts=chunk_texts,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                emit=emit,
                monitor=monitor,
            )
            monitor.export_json()
            return parsed_chunk

    def process_document_chunks(
        self,
        *,
        chunk_texts: Sequence[str],
        doc_name: str,
        doc_time: str,
        group_id: str = "default",
        doc_id: str,
        existing_chunks: Optional[Sequence[ChunkExtractionParsed]] = None,
        event_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
        chunk_result_callback: Optional[
            Callable[[Chunk, int, int, str, Optional[ChunkExtractionParsed], str], None]
        ] = None,
    ) -> tuple[List[ChunkExtractionParsed], List[Dict[str, object]], List[Dict[str, object]]]:
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
            chunks = [Chunk(chunk_id=f"{doc_id}::chunk_{index}", text=chunk_text) for index, chunk_text in enumerate(chunk_texts, 1)]
            existing_chunk_map = {chunk.chunk_id: chunk for chunk in (existing_chunks or [])}
            parsed_chunks: List[ChunkExtractionParsed] = []
            extraction_samples: List[Dict[str, object]] = []
            parsing_samples: List[Dict[str, object]] = []

            for chunk_number, chunk in enumerate(chunks, 1):
                total_chunks = len(chunks)
                chunk_index = chunk_number - 1
                cached_chunk = existing_chunk_map.get(chunk.chunk_id)
                if cached_chunk is not None:
                    parsed_chunks.append(cached_chunk)
                    emit(
                        "chunk.restored",
                        "chunk_resume",
                        message=f"restored chunk {chunk_number}/{total_chunks} from checkpoint",
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

                if chunk_result_callback is not None:
                    chunk_result_callback(chunk, chunk_index, total_chunks, "processing", None, "")

                parsed_chunk = self._run_chunk_pipeline(
                    chunk=chunk,
                    chunk_texts=chunk_texts,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    emit=lambda event_type, stage, *, message, payload=None: emit(
                        event_type,
                        stage,
                        message=message,
                        chunk_id=chunk.chunk_id,
                        chunk_index=chunk_index,
                        total_chunks=total_chunks,
                        payload=payload,
                    ),
                    monitor=monitor,
                )
                parsed_chunks.append(parsed_chunk)
                extraction_samples.append(
                    {
                        "chunk_id": parsed_chunk.chunk_id,
                        "error": parsed_chunk.error,
                        "raw_preview": (parsed_chunk.entity_relation_raw or "")[:500],
                    }
                )
                parsing_samples.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "entities": [entity.name for entity in parsed_chunk.parsed.entities[:20]],
                        "relations": [
                            {
                                "s": relation.subject,
                                "o": relation.object,
                                "t": relation.relation_type,
                                "c": relation.confidence,
                            }
                            for relation in parsed_chunk.parsed.relations[:20]
                        ],
                        "errors": parsed_chunk.parsed.errors[:20],
                    }
                )
                if chunk_result_callback is not None:
                    chunk_result_callback(
                        chunk,
                        chunk_index,
                        total_chunks,
                        "failed" if parsed_chunk.error else "completed",
                        parsed_chunk,
                        parsed_chunk.error or "",
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
            return parsed_chunks, extraction_samples, parsing_samples

    def _run_chunk_pipeline(
        self,
        *,
        chunk: Chunk,
        chunk_texts: Sequence[str],
        chunk_index: int,
        total_chunks: int,
        emit: Callable[[str, str], None],
        monitor: MonitoringManager,
    ) -> ChunkExtractionParsed:
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
            if chunk_coref.error:
                monitor.inc("coreference_resolution.errors", 1)

        emit(
            "chunk.coref.done",
            "chunk_coreference",
            message=f"chunk {chunk_index + 1}/{total_chunks} coreference resolved",
            payload={"error": chunk_coref.error, "resolved_chars": len(chunk_coref.resolved_text or "")},
        )

        with monitor.span("entity_relation_extraction", chunk_id=chunk.chunk_id):
            extracted = asyncio.run(
                extractor.extract_one(Chunk(chunk_id=chunk.chunk_id, text=chunk_coref.resolved_text))
            )
            monitor.observe("entity_relation_extraction.results", 1.0)
            if extracted.error:
                monitor.observe("entity_relation_extraction.chunk_errors", 1.0)

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
            monitor.observe("entity_relation_parsing.entities", float(len(parsed.entities)))
            monitor.observe("entity_relation_parsing.relations", float(len(parsed.relations)))
            monitor.observe("entity_relation_parsing.parse_errors", float(len(parsed.errors)))

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
        return parsed_chunk
