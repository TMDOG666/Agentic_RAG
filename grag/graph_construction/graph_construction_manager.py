from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Optional, Sequence

from grag.monitoring.monitoring_manager import MonitoringManager, use_monitor

from .chunk_processor import GraphChunkProcessor
from .chunker import SemanticChunker
from .document_fusion import DocumentFusionProcessor
from .types import (
    ChunkExtractionParsed,
    GraphConstructionInput,
    GraphConstructionResult,
    GraphConstructionStreamEvent,
)


class GraphConstructionManager:
    """图谱构建编排器。

    现在这个类只负责：
    - 文档级 chunking
    - 串联 chunk 处理层
    - 串联文档级融合层
    """

    def __init__(
        self,
        *,
        coref_llm_chat_fn: Optional[Callable[[str], str]] = None,
        entity_relation_llm_chat_fn: Optional[Callable[[str], str]] = None,
        fusion_llm_chat_fn: Optional[Callable[[str], str]] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
    ) -> None:
        self._chunk_processor = GraphChunkProcessor(
            coref_llm_chat_fn=coref_llm_chat_fn,
            entity_relation_llm_chat_fn=entity_relation_llm_chat_fn,
        )
        self._fusion_processor = DocumentFusionProcessor(
            fusion_llm_chat_fn=fusion_llm_chat_fn,
            embedding_fn=embedding_fn,
        )

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
        return self._chunk_processor.process_single_chunk(
            chunk_texts=chunk_texts,
            chunk_index=chunk_index,
            doc_name=doc_name,
            doc_time=doc_time,
            group_id=group_id,
            doc_id=doc_id,
            event_callback=event_callback,
        )

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
            Callable[[object, int, int, str, Optional[ChunkExtractionParsed], str], None]
        ] = None,
    ) -> GraphConstructionResult:
        final_doc_id = doc_id or uuid.uuid4().hex

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
                    doc_id=final_doc_id,
                    doc_name=doc_name,
                    group_id=group_id,
                    total_chunks=total_chunks,
                    message=message,
                    payload=payload,
                )
            )

        monitor = MonitoringManager(
            doc_name=doc_name,
            base_attrs={"doc_time": doc_time, "group_id": group_id, "doc_id": final_doc_id},
        )
        with use_monitor(monitor):
            final_chunk_texts = self._chunk_document(
                text=text,
                chunk_texts=chunk_texts,
                emit=emit,
                monitor=monitor,
            )
            parsed_chunks, _, _ = self._chunk_processor.process_document_chunks(
                chunk_texts=final_chunk_texts,
                doc_name=doc_name,
                doc_time=doc_time,
                group_id=group_id,
                doc_id=final_doc_id,
                existing_chunks=existing_chunks,
                event_callback=event_callback,
                chunk_result_callback=chunk_result_callback,
            )
            return self._fusion_processor.fuse_document(
                parsed_chunks=parsed_chunks,
                text=text,
                doc_name=doc_name,
                doc_time=doc_time,
                group_id=group_id,
                doc_id=final_doc_id,
                event_callback=event_callback,
            )

    @staticmethod
    def _chunk_document(
        *,
        text: str,
        chunk_texts: Optional[Sequence[str]],
        emit: Callable[[str, str], None],
        monitor: MonitoringManager,
    ) -> List[str]:
        with monitor.span("chunking"):
            final_chunk_texts = list(chunk_texts or [])
            if not final_chunk_texts:
                final_chunk_texts = SemanticChunker().chunk(text)
            monitor.observe("chunking.chunks", float(len(final_chunk_texts)))
        monitor.record_result(
            "chunking",
            {
                "chunks": len(final_chunk_texts),
                "chunk_chars": [len(item) for item in final_chunk_texts[:50]],
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
        return final_chunk_texts


__all__ = [
    "ChunkExtractionParsed",
    "GraphConstructionInput",
    "GraphConstructionManager",
    "GraphConstructionResult",
    "GraphConstructionStreamEvent",
]
