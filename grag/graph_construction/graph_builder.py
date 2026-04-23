from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4, uuid5

from ..model.embedding_client import EmbeddingClient
from ..model.llm_client import LLMClient
from ..storage import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    EntityMentionRecord,
    EntityAlignmentRecord,
    GraphChunkCheckpointRecord,
    GraphPipelineCheckpointRecord,
    GlobalRelationRecord,
    GraphEntityRecord,
    GraphIndexRecord,
    GraphRelationRecord,
    GraphStorage,
    GlobalEntityRecord,
    RelationMentionRecord,
    RelationAlignmentRecord,
)
from .chunker import SemanticChunker
from .graph_construction_manager import (
    ChunkExtractionParsed,
    GraphConstructionManager,
    GraphConstructionResult,
    GraphConstructionStreamEvent,
)
from .entity_relation_parser import ParsedEntity, ParsedEntityRelation, ParsedRelation


GRAG_NAMESPACE = UUID("6b45223b-b3b8-4a2f-b7b7-3d6ad9d2f3f0")


@dataclass(frozen=True)
class BaseDocumentBuildResult:
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]


@dataclass(frozen=True)
class GraphBuildResult:
    construction: GraphConstructionResult
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]
    entities: List[GraphEntityRecord]
    relations: List[GraphRelationRecord]
    entity_mentions: List[EntityMentionRecord]
    relation_mentions: List[RelationMentionRecord]
    global_entities: List[GlobalEntityRecord]
    entity_alignments: List[EntityAlignmentRecord]
    global_relations: List[GlobalRelationRecord]
    relation_alignments: List[RelationAlignmentRecord]


@dataclass(frozen=True)
class GraphBuildPreparation:
    final_doc_id: str
    existing_chunks: List[ChunkRecord]
    restored_chunks: List[ChunkExtractionParsed]
    pipeline_map: Dict[str, GraphPipelineCheckpointRecord]
    total_chunk_count: int


@dataclass(frozen=True)
class GraphAssetBundle:
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]
    entities: List[GraphEntityRecord]
    relations: List[GraphRelationRecord]
    entity_mentions: List[EntityMentionRecord]
    relation_mentions: List[RelationMentionRecord]
    global_entities: List[GlobalEntityRecord]
    entity_alignments: List[EntityAlignmentRecord]
    global_relations: List[GlobalRelationRecord]
    relation_alignments: List[RelationAlignmentRecord]


class GraphBuilder:
    def __init__(
        self,
        *,
        storage: GraphStorage,
        construction_manager: Optional[GraphConstructionManager] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
        embedding_provider: Optional[str] = None,
        llm_chat_fn: Optional[Callable[[str], str]] = None,
        llm_provider: Optional[str] = None,
    ) -> None:
        self._storage = storage
        self._manager = construction_manager or GraphConstructionManager()
        self._embedding_fn = embedding_fn
        self._embedding_provider = embedding_provider
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)
        self._llm_chat_fn = llm_chat_fn
        self._llm_provider = llm_provider

    def build_base_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> BaseDocumentBuildResult:
        final_doc_id = str(doc_id or uuid4().hex)
        chunk_texts = SemanticChunker().chunk(text)
        chunks = [
            ChunkRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=f"{final_doc_id}::chunk_{i}",
                index=i - 1,
                text=t,
            )
            for i, t in enumerate(chunk_texts, 1)
        ]
        vectors = self._embed_texts([c.text for c in chunks])
        embeddings = [
            ChunkEmbeddingRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=chunks[i].chunk_id,
                vector=vec,
            )
            for i, vec in enumerate(vectors)
        ]
        document = DocumentRecord(
            group_id=group_id,
            doc_id=final_doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            metadata={"original_length": len(text), "ingest_stage": "base_completed"},
        )
        self._storage.save_base_document(document=document, chunks=chunks, embeddings=embeddings)
        return BaseDocumentBuildResult(document=document, chunks=chunks, embeddings=embeddings)

    def build_graph_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
        progress_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
        stream_base: bool = False,
    ) -> GraphBuildResult:
        preparation = self._prepare_graph_build(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
        )
        final_doc_id = preparation.final_doc_id
        active_stage = "chunk_resume"

        def _on_event(event: GraphConstructionStreamEvent) -> None:
            if progress_callback is not None:
                progress_callback(event)

        def _on_chunk_result(
            chunk,
            chunk_index: int,
            total_chunks: int,
            status: str,
            parsed_chunk: Optional[ChunkExtractionParsed],
            error: str,
        ) -> None:
            checkpoint = self._build_chunk_checkpoint(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk_index,
                status=status,
                parsed_chunk=parsed_chunk,
                error=error,
            )
            self._storage.upsert_graph_chunk_checkpoint(checkpoint=checkpoint)

        try:
            self._upsert_pipeline_checkpoint(
                group_id=group_id,
                doc_id=final_doc_id,
                stage="fusion",
                status="processing",
                payload={
                    "restored_chunks": len(preparation.restored_chunks),
                    "total_chunks": preparation.total_chunk_count,
                    "previous_status": preparation.pipeline_map.get("fusion").status
                    if preparation.pipeline_map.get("fusion") is not None
                    else "",
                },
            )
            active_stage = "fusion"
            construction = self._manager.run_stream(
                text=text,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=final_doc_id,
                event_callback=_on_event if (stream_base or progress_callback is not None) else None,
                existing_chunks=preparation.restored_chunks,
                chunk_texts=[chunk.text for chunk in preparation.existing_chunks],
                chunk_result_callback=_on_chunk_result,
            )
            self._upsert_pipeline_checkpoint(
                group_id=group_id,
                doc_id=final_doc_id,
                stage="fusion",
                status="completed",
                payload={
                    "fused_entities": len(getattr(construction.graph.get("intra_document_fusion"), "fused_entities", []))
                    if isinstance(construction.graph, dict) and construction.graph.get("intra_document_fusion") is not None
                    else 0,
                    "rewritten_relations": len(getattr(construction.graph.get("intra_document_fusion"), "rewritten_relations", []))
                    if isinstance(construction.graph, dict) and construction.graph.get("intra_document_fusion") is not None
                    else 0,
                },
            )
            asset_bundle = self._build_and_save_graph_assets(
                construction=construction,
                group_id=group_id,
                doc_id=final_doc_id,
                doc_name=doc_name,
                doc_time=doc_time,
                original_text=text,
                total_chunk_count=preparation.total_chunk_count,
            )
        except Exception as exc:
            self._upsert_pipeline_checkpoint(
                group_id=group_id,
                doc_id=final_doc_id,
                stage=active_stage,
                status="failed",
                payload={},
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        return GraphBuildResult(
            construction=construction,
            document=asset_bundle.document,
            chunks=asset_bundle.chunks,
            embeddings=asset_bundle.embeddings,
            entities=asset_bundle.entities,
            relations=asset_bundle.relations,
            entity_mentions=asset_bundle.entity_mentions,
            relation_mentions=asset_bundle.relation_mentions,
            global_entities=asset_bundle.global_entities,
            entity_alignments=asset_bundle.entity_alignments,
            global_relations=asset_bundle.global_relations,
            relation_alignments=asset_bundle.relation_alignments,
        )

    def build_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphBuildResult:
        return self.build_graph_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
            stream_base=True,
        )

    def _prepare_graph_build(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str,
        doc_id: Optional[str],
    ) -> GraphBuildPreparation:
        final_doc_id = str(doc_id or uuid4().hex)
        existing_chunks = list(self._storage.list_doc_chunks(group_id=group_id, doc_id=final_doc_id, limit=200000))
        checkpoint_rows = list(self._storage.list_graph_chunk_checkpoints(group_id=group_id, doc_id=final_doc_id))
        pipeline_rows = list(self._storage.list_graph_pipeline_checkpoints(group_id=group_id, doc_id=final_doc_id))
        restored_chunks = self._restore_completed_chunks(
            checkpoints=checkpoint_rows,
            group_id=group_id,
            doc_id=final_doc_id,
            chunks=existing_chunks,
        )
        total_chunk_count = len(existing_chunks)
        if not existing_chunks:
            base = self.build_base_and_save(
                text=text,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=final_doc_id,
            )
            existing_chunks = list(base.chunks)
            total_chunk_count = len(existing_chunks)
        return GraphBuildPreparation(
            final_doc_id=final_doc_id,
            existing_chunks=existing_chunks,
            restored_chunks=restored_chunks,
            pipeline_map={row.stage: row for row in pipeline_rows},
            total_chunk_count=total_chunk_count,
        )

    def _build_and_save_graph_assets(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        original_text: str,
        total_chunk_count: int,
    ) -> GraphAssetBundle:
        document = self._build_document_record(
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            original_length=len(original_text),
            ingest_stage="graph_built",
            extra_metadata={
                "total_chunks": total_chunk_count or len(construction.chunks),
                "graph_checkpoint_completed": sum(1 for chunk in construction.chunks if not chunk.error),
                "graph_checkpoint_failed": sum(1 for chunk in construction.chunks if chunk.error),
            },
        )
        chunks = [
            ChunkRecord(
                group_id=group_id,
                doc_id=doc_id,
                chunk_id=chunk.chunk_id,
                index=index,
                text=chunk.text,
            )
            for index, chunk in enumerate(construction.chunks)
        ]
        embeddings: List[ChunkEmbeddingRecord] = []

        entities, relations = self._run_doc_graph_asset_stage(
            construction=construction,
            group_id=group_id,
            doc_id=doc_id,
        )
        global_entities, entity_alignments, entities, relations = self._run_entity_alignment_stage(
            group_id=group_id,
            doc_id=doc_id,
            entities=entities,
            relations=relations,
        )
        entities = [self._with_entity_id(entity) for entity in entities]
        relations = [self._with_relation_id(relation) for relation in relations]
        global_relations, relation_alignments = self._run_relation_alignment_stage(
            group_id=group_id,
            doc_id=doc_id,
            global_entities=global_entities,
            relations=relations,
        )
        entity_mentions, relation_mentions = self._run_mentions_stage(
            construction=construction,
            group_id=group_id,
            doc_id=doc_id,
            entities=entities,
            global_entities=global_entities,
            relations=relations,
            global_relations=global_relations,
        )
        graph_index_records = self._run_graph_index_stage(
            group_id=group_id,
            doc_id=doc_id,
            entities=entities,
            relations=relations,
            global_entities=global_entities,
            global_relations=global_relations,
        )
        self._run_save_graph_assets_stage(
            group_id=group_id,
            doc_id=doc_id,
            document=document,
            entities=entities,
            relations=relations,
            entity_mentions=entity_mentions,
            relation_mentions=relation_mentions,
            global_entities=global_entities,
            entity_alignments=entity_alignments,
            global_relations=global_relations,
            relation_alignments=relation_alignments,
            graph_index_records=graph_index_records,
        )
        return GraphAssetBundle(
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
            entity_mentions=entity_mentions,
            relation_mentions=relation_mentions,
            global_entities=global_entities,
            entity_alignments=entity_alignments,
            global_relations=global_relations,
            relation_alignments=relation_alignments,
        )

    def retry_single_chunk(
        self,
        *,
        group_id: str,
        doc_id: str,
        chunk_id: str,
        doc_name: str,
        doc_time: str,
        event_callback: Optional[Callable[[GraphConstructionStreamEvent], None]] = None,
    ) -> ChunkExtractionParsed:
        chunks = list(self._storage.list_doc_chunks(group_id=group_id, doc_id=doc_id, limit=200000))
        if not chunks:
            raise ValueError(f"document chunks not found: group_id={group_id}, doc_id={doc_id}")

        chunk_index = next((idx for idx, item in enumerate(chunks) if item.chunk_id == chunk_id), -1)
        if chunk_index < 0:
            raise ValueError(f"chunk not found: group_id={group_id}, doc_id={doc_id}, chunk_id={chunk_id}")

        target_chunk = chunks[chunk_index]
        self._storage.upsert_graph_chunk_checkpoint(
            checkpoint=GraphChunkCheckpointRecord(
                group_id=group_id,
                doc_id=doc_id,
                chunk_id=target_chunk.chunk_id,
                chunk_index=chunk_index,
                status="processing",
                resolved_text="",
                entity_relation_raw="",
                parsed_json={},
                error="",
                updated_at=self._now(),
            )
        )

        parsed_chunk: Optional[ChunkExtractionParsed] = None
        try:
            parsed_chunk = self._manager.process_single_chunk(
                chunk_texts=[item.text for item in chunks],
                chunk_index=chunk_index,
                doc_name=doc_name,
                doc_time=doc_time,
                group_id=group_id,
                doc_id=doc_id,
                event_callback=event_callback,
            )
            final_status = "completed" if not str(parsed_chunk.error or "").strip() else "failed"
            self._storage.upsert_graph_chunk_checkpoint(
                checkpoint=self._build_chunk_checkpoint(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=target_chunk.chunk_id,
                    chunk_index=chunk_index,
                    status=final_status,
                    parsed_chunk=parsed_chunk,
                    error=str(parsed_chunk.error or ""),
                )
            )
            return parsed_chunk
        except Exception as exc:
            self._storage.upsert_graph_chunk_checkpoint(
                checkpoint=self._build_chunk_checkpoint(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=target_chunk.chunk_id,
                    chunk_index=chunk_index,
                    status="failed",
                    parsed_chunk=parsed_chunk,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._embedding_fn is not None:
            provider = self._embedding_provider or "default"
            return self._embedding_fn(texts, provider)
        return self._embedding_client.embed_texts(texts)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _build_chunk_checkpoint(
        self,
        *,
        group_id: str,
        doc_id: str,
        chunk_id: str,
        chunk_index: int,
        status: str,
        parsed_chunk: Optional[ChunkExtractionParsed],
        error: str,
    ) -> GraphChunkCheckpointRecord:
        return GraphChunkCheckpointRecord(
            group_id=group_id,
            doc_id=doc_id,
            chunk_id=chunk_id,
            chunk_index=chunk_index,
            status=status,
            resolved_text=parsed_chunk.resolved_text if parsed_chunk is not None else "",
            entity_relation_raw=parsed_chunk.entity_relation_raw if parsed_chunk is not None else "",
            parsed_json=self._serialize_parsed(parsed_chunk.parsed) if parsed_chunk is not None else {},
            error=str(error or ""),
            updated_at=self._now(),
        )

    def _run_doc_graph_asset_stage(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
    ) -> tuple[List[GraphEntityRecord], List[GraphRelationRecord]]:
        stage = "doc_graph_assets"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        entities, relations = self._build_doc_level_graph_assets(
            construction=construction,
            group_id=group_id,
            doc_id=doc_id,
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={"entities": len(entities), "relations": len(relations)},
        )
        return entities, relations

    def _run_entity_alignment_stage(
        self,
        *,
        group_id: str,
        doc_id: str,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> tuple[
        List[GlobalEntityRecord],
        List[EntityAlignmentRecord],
        List[GraphEntityRecord],
        List[GraphRelationRecord],
    ]:
        stage = "entity_alignment"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        global_entities, entity_alignments, rewritten_entities, rewritten_relations, llm_compare_failed_count = (
            self._align_entities_to_global(
                group_id=group_id,
                doc_id=doc_id,
                new_entities=entities,
                relations=relations,
            )
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={
                "global_entities": len(global_entities),
                "entity_alignments": len(entity_alignments),
                "rewritten_entities": len(rewritten_entities),
                "rewritten_relations": len(rewritten_relations),
                "llm_compare_failed_count": llm_compare_failed_count,
            },
        )
        return global_entities, entity_alignments, rewritten_entities, rewritten_relations

    def _run_relation_alignment_stage(
        self,
        *,
        group_id: str,
        doc_id: str,
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> tuple[List[GlobalRelationRecord], List[RelationAlignmentRecord]]:
        stage = "relation_alignment"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        global_relations, relation_alignments = self._align_relations_to_global(
            group_id=group_id,
            doc_id=doc_id,
            global_entities=global_entities,
            relations=relations,
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={
                "global_relations": len(global_relations),
                "relation_alignments": len(relation_alignments),
            },
        )
        return global_relations, relation_alignments

    def _run_mentions_stage(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
        entities: Sequence[GraphEntityRecord],
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> tuple[List[EntityMentionRecord], List[RelationMentionRecord]]:
        stage = "mentions"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        entity_mentions, relation_mentions = self._build_mentions(
            construction=construction,
            group_id=group_id,
            doc_id=doc_id,
            entities=entities,
            global_entities=global_entities,
            relations=relations,
            global_relations=global_relations,
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={
                "entity_mentions": len(entity_mentions),
                "relation_mentions": len(relation_mentions),
            },
        )
        return entity_mentions, relation_mentions

    def _run_graph_index_stage(
        self,
        *,
        group_id: str,
        doc_id: str,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_entities: Sequence[GlobalEntityRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> List[GraphIndexRecord]:
        stage = "graph_index"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        graph_index_records = self._build_graph_index_records(
            entities=entities,
            relations=relations,
            global_entities=global_entities,
            global_relations=global_relations,
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={"graph_index_records": len(graph_index_records)},
        )
        return graph_index_records

    def _run_save_graph_assets_stage(
        self,
        *,
        group_id: str,
        doc_id: str,
        document: DocumentRecord,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        entity_mentions: Sequence[EntityMentionRecord],
        relation_mentions: Sequence[RelationMentionRecord],
        global_entities: Sequence[GlobalEntityRecord],
        entity_alignments: Sequence[EntityAlignmentRecord],
        global_relations: Sequence[GlobalRelationRecord],
        relation_alignments: Sequence[RelationAlignmentRecord],
        graph_index_records: Sequence[GraphIndexRecord],
    ) -> None:
        stage = "save_graph_assets"
        self._upsert_pipeline_checkpoint(group_id=group_id, doc_id=doc_id, stage=stage, status="processing")
        self._storage.save_graph_assets(
            document=document,
            entities=entities,
            relations=relations,
            entity_mentions=entity_mentions,
            relation_mentions=relation_mentions,
            global_entities=global_entities,
            entity_alignments=entity_alignments,
            global_relations=global_relations,
            relation_alignments=relation_alignments,
            graph_index_records=graph_index_records,
        )
        self._upsert_pipeline_checkpoint(
            group_id=group_id,
            doc_id=doc_id,
            stage=stage,
            status="completed",
            payload={"saved": True},
        )

    @staticmethod
    def _serialize_parsed(parsed: ParsedEntityRelation) -> Dict[str, object]:
        return {
            "entities": [
                {
                    "name": entity.name,
                    "type": entity.type,
                    "description": entity.description,
                }
                for entity in parsed.entities
            ],
            "relations": [
                {
                    "subject": relation.subject,
                    "object": relation.object,
                    "description": relation.description,
                    "relation_type": relation.relation_type,
                    "confidence": relation.confidence,
                }
                for relation in parsed.relations
            ],
            "errors": list(parsed.errors),
        }
    
    @classmethod
    def _deserialize_parsed(cls, payload: Dict[str, object]) -> ParsedEntityRelation:
        entity_rows = payload.get("entities") if isinstance(payload, dict) else []
        relation_rows = payload.get("relations") if isinstance(payload, dict) else []
        error_rows = payload.get("errors") if isinstance(payload, dict) else []
        entities = [
            ParsedEntity(
                name=str(item.get("name") or "").strip(),
                type=str(item.get("type") or "").strip(),
                description=str(item.get("description") or "").strip(),
            )
            for item in entity_rows
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        relations = [
            ParsedRelation(
                subject=str(item.get("subject") or "").strip(),
                object=str(item.get("object") or "").strip(),
                description=str(item.get("description") or "").strip(),
                relation_type=str(item.get("relation_type") or "").strip(),
                confidence=cls._coerce_confidence(item.get("confidence")),
            )
            for item in relation_rows
            if isinstance(item, dict)
            and str(item.get("subject") or "").strip()
            and str(item.get("object") or "").strip()
        ]
        errors = [str(item) for item in error_rows] if isinstance(error_rows, list) else []
        return ParsedEntityRelation(entities=entities, relations=relations, errors=errors)

    @staticmethod
    def _coerce_confidence(value: object) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _restore_completed_chunks(
        self,
        *,
        checkpoints: Sequence[GraphChunkCheckpointRecord],
        group_id: str,
        doc_id: str,
        chunks: Sequence[ChunkRecord],
    ) -> List[ChunkExtractionParsed]:
        chunk_text_by_id = {chunk.chunk_id: chunk.text for chunk in chunks}
        restored: List[ChunkExtractionParsed] = []
        for checkpoint in checkpoints:
            if checkpoint.status != "completed":
                continue
            chunk_text = chunk_text_by_id.get(checkpoint.chunk_id, "")
            restored.append(
                ChunkExtractionParsed(
                    chunk_id=checkpoint.chunk_id,
                    text=chunk_text,
                    resolved_text=checkpoint.resolved_text,
                    entity_relation_raw=checkpoint.entity_relation_raw,
                    parsed=self._deserialize_parsed(checkpoint.parsed_json or {}),
                    error=None,
                )
            )
        restored.sort(key=lambda item: next((c.index for c in chunks if c.chunk_id == item.chunk_id), 0))
        return restored

    def _upsert_pipeline_checkpoint(
        self,
        *,
        group_id: str,
        doc_id: str,
        stage: str,
        status: str,
        payload: Optional[Dict[str, object]] = None,
        error: str = "",
    ) -> None:
        self._storage.upsert_graph_pipeline_checkpoint(
            checkpoint=GraphPipelineCheckpointRecord(
                group_id=group_id,
                doc_id=doc_id,
                stage=stage,
                status=status,
                payload_json=dict(payload or {}),
                error=error,
                updated_at=self._now(),
            )
        )

    @staticmethod
    def _build_document_record(
        *,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
        original_length: int,
        ingest_stage: str,
        extra_metadata: Optional[Dict[str, object]] = None,
    ) -> DocumentRecord:
        metadata: Dict[str, object] = {
            "original_length": original_length,
            "ingest_stage": ingest_stage,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return DocumentRecord(
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            metadata=metadata,
        )

    def _build_doc_level_graph_assets(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
    ) -> tuple[List[GraphEntityRecord], List[GraphRelationRecord]]:
        fusion = None
        if construction.graph and isinstance(construction.graph, dict):
            fusion = construction.graph.get("intra_document_fusion")

        entities: List[GraphEntityRecord] = []
        relations: List[GraphRelationRecord] = []
        if fusion is None:
            return entities, relations

        entities = [
            GraphEntityRecord(
                entity_id="",
                group_id=group_id,
                doc_id=doc_id,
                canonical_name=fe.canonical_name,
                type=fe.type,
                aliases=list(fe.aliases),
                description=fe.description,
            )
            for fe in getattr(fusion, "fused_entities", [])
        ]
        relations = [
            GraphRelationRecord(
                relation_id="",
                group_id=group_id,
                doc_id=doc_id,
                subject=r.subject,
                object=r.object,
                relation_type=r.relation_type,
                description=r.description,
                confidence=r.confidence,
            )
            for r in getattr(fusion, "rewritten_relations", [])
        ]
        return entities, relations

    @staticmethod
    def _global_entity_id(*, group_id: str, canonical_name: str) -> str:
        return str(uuid5(GRAG_NAMESPACE, f"{group_id}:global:{canonical_name}"))

    @staticmethod
    def _with_entity_id(e: GraphEntityRecord) -> GraphEntityRecord:
        return GraphEntityRecord(
            entity_id=str(uuid5(GRAG_NAMESPACE, f"{e.group_id}:{e.doc_id}:{e.canonical_name}")),
            group_id=e.group_id,
            doc_id=e.doc_id,
            canonical_name=e.canonical_name,
            type=e.type,
            aliases=list(e.aliases),
            description=e.description,
        )

    @staticmethod
    def _with_relation_id(r: GraphRelationRecord) -> GraphRelationRecord:
        return GraphRelationRecord(
            relation_id=str(uuid5(GRAG_NAMESPACE, f"{r.group_id}:{r.doc_id}:{r.subject}:{r.relation_type}:{r.object}")),
            group_id=r.group_id,
            doc_id=r.doc_id,
            subject=r.subject,
            object=r.object,
            relation_type=r.relation_type,
            description=r.description,
            confidence=r.confidence,
        )

    def _build_graph_index_records(
        self,
        *,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_entities: Sequence[GlobalEntityRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> List[GraphIndexRecord]:
        records: List[GraphIndexRecord] = []
        texts: List[str] = []
        meta: List[tuple[str, object]] = []

        for e in entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            texts.append(f"{e.canonical_name}\n{aliases}\n{e.description}".strip())
            meta.append(("entity", e))
        for r in relations:
            texts.append(f"{r.subject} -[{r.relation_type}]-> {r.object}\n{r.description}".strip())
            meta.append(("relation", r))
        for e in global_entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            texts.append(f"{e.canonical_name}\n{aliases}\n{e.description}".strip())
            meta.append(("global_entity", e))
        for r in global_relations:
            texts.append(f"{r.subject_name} -[{r.relation_type}]-> {r.object_name}\n{r.description}".strip())
            meta.append(("global_relation", r))

        vectors = self._embed_texts(texts) if texts else []
        for (kind, obj), vec, raw_text in zip(meta, vectors, texts):
            if kind == "entity":
                e = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"e:{e.group_id}:{e.doc_id}:{e.entity_id}",
                        kind="entity",
                        group_id=e.group_id,
                        doc_id=e.doc_id,
                        source_id=e.entity_id,
                        name=e.canonical_name,
                        text=raw_text,
                        embedding=list(vec),
                    )
                )
            else:
                if kind == "relation":
                    r = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"r:{r.group_id}:{r.doc_id}:{r.relation_id}",
                            kind="relation",
                            group_id=r.group_id,
                            doc_id=r.doc_id,
                            source_id=r.relation_id,
                            name=r.relation_type,
                            text=raw_text,
                            embedding=list(vec),
                            head_name=r.subject,
                            tail_name=r.object,
                            relation_type=r.relation_type,
                        )
                    )
                elif kind == "global_entity":
                    e = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"e:{e.group_id}:__global__:{e.global_entity_id}",
                            kind="entity",
                            group_id=e.group_id,
                            doc_id="__global__",
                            source_id=e.global_entity_id,
                            name=e.canonical_name,
                            text=raw_text,
                            embedding=list(vec),
                        )
                    )
                else:
                    r = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"r:{r.group_id}:__global__:{r.global_relation_id}",
                            kind="relation",
                            group_id=r.group_id,
                            doc_id="__global__",
                            source_id=r.global_relation_id,
                            name=r.relation_type,
                            text=raw_text,
                            embedding=list(vec),
                            head_name=r.subject_name,
                            tail_name=r.object_name,
                            relation_type=r.relation_type,
                        )
                    )
        return records

    def _align_entities_to_global(
        self,
        *,
        group_id: str,
        doc_id: str,
        new_entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        vector_threshold: float = 0.90,
        vector_uncertain_gap: float = 0.05,
    ) -> tuple[
        List[GlobalEntityRecord],
        List[EntityAlignmentRecord],
        List[GraphEntityRecord],
        List[GraphRelationRecord],
        int,
    ]:
        if not new_entities:
            return [], [], list(new_entities), list(relations), 0

        old_entities = list(self._storage.list_group_global_entities(group_id=group_id, limit=2000))

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        def _entity_text(name: str, etype: str, aliases: Sequence[str], description: str) -> str:
            return f"{name}\n{etype}\n{' '.join([a for a in aliases if a])}\n{description}".strip()

        def _cos_sim(a: Sequence[float], b: Sequence[float]) -> float:
            if not a or not b or len(a) != len(b):
                return -1.0
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += float(x) * float(y)
                na += float(x) * float(x)
                nb += float(y) * float(y)
            if na <= 0.0 or nb <= 0.0:
                return -1.0
            return dot / (math.sqrt(na) * math.sqrt(nb))

        def _desc_gap(a: str, b: str) -> float:
            la = len((a or "").strip())
            lb = len((b or "").strip())
            if la <= 0 and lb <= 0:
                return 0.0
            return float(max(la, lb)) / float(max(1, min(la, lb)))

        def _llm_same_entity_and_merge(
            *,
            incoming: GraphEntityRecord,
            candidate: GlobalEntityRecord,
        ) -> Tuple[bool, Optional[GlobalEntityRecord], bool]:
            prompt = (
                "你是实体对齐与知识融合助手。\n"
                "判断 new_entity 与 global_entity 是否是同一真实实体。\n"
                "如果不是，输出 JSON: {\"same\": false}\n"
                "如果是，输出 JSON: "
                "{\"same\": true, \"canonical_name\": <string>, \"type\": <string>, \"aliases\": <list[string]>, \"description\": <string>}\n"
                "只输出 JSON。\n\n"
                "new_entity:\n"
                + json.dumps(
                    {
                        "name": incoming.canonical_name,
                        "type": incoming.type,
                        "aliases": list(incoming.aliases),
                        "description": incoming.description,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + "global_entity:\n"
                + json.dumps(
                    {
                        "name": candidate.canonical_name,
                        "type": candidate.type,
                        "aliases": list(candidate.aliases),
                        "description": candidate.description,
                    },
                    ensure_ascii=False,
                )
            )
            chat = self._llm_chat_fn or LLMClient(self._llm_provider).chat
            try:
                raw = (chat(prompt) or "").strip()
                data = json.loads(raw)
            except Exception:
                return False, None, True
            if not isinstance(data, dict) or not bool(data.get("same")):
                return False, None, False
            merged = GlobalEntityRecord(
                global_entity_id=candidate.global_entity_id,
                group_id=group_id,
                canonical_name=str(data.get("canonical_name") or candidate.canonical_name).strip(),
                type=str(data.get("type") or candidate.type).strip(),
                aliases=[
                    str(x).strip()
                    for x in (data.get("aliases") or [])
                    if str(x).strip()
                ],
                description=str(data.get("description") or candidate.description or incoming.description).strip(),
            )
            return True, merged, False

        old_by_name: Dict[str, GlobalEntityRecord] = {}
        for oe in old_entities:
            old_by_name.setdefault(_norm(oe.canonical_name), oe)
            for a in oe.aliases:
                old_by_name.setdefault(_norm(a), oe)

        old_vecs: Dict[str, List[float]] = {}
        if old_entities:
            old_vectors = self._embed_texts(
                [
                    _entity_text(oe.canonical_name, oe.type, oe.aliases, oe.description)
                    for oe in old_entities
                ]
            )
            for oe, vec in zip(old_entities, old_vectors):
                old_vecs[_norm(oe.canonical_name)] = list(vec)

        global_out: Dict[str, GlobalEntityRecord] = { _norm(e.canonical_name): e for e in old_entities }
        alias_map: Dict[str, str] = {}
        alignments: List[EntityAlignmentRecord] = []
        rewritten_entities: List[GraphEntityRecord] = []
        llm_compare_failed_count = 0

        for ne in new_entities:
            key = _norm(ne.canonical_name)
            hit = old_by_name.get(key)
            hit_from_alias = False
            type_conflict = False
            desc_gap = 0.0
            score: Optional[float] = None
            method = "new_global"

            if hit is None:
                for a in ne.aliases:
                    hit = old_by_name.get(_norm(a))
                    if hit is not None:
                        hit_from_alias = True
                        break

            if hit is not None:
                type_conflict = _norm(hit.type) not in {"", _norm(ne.type)}
                desc_gap = _desc_gap(hit.description, ne.description)
                method = "name_match"

            vector_candidate: Optional[GlobalEntityRecord] = None
            if hit is None and old_entities:
                ne_vec = self._embed_texts(
                    [_entity_text(ne.canonical_name, ne.type, ne.aliases, ne.description)]
                )[0]
                best_score = -1.0
                best_entity: Optional[GlobalEntityRecord] = None
                for oe in old_entities:
                    if _norm(oe.type) and _norm(ne.type) and _norm(oe.type) != _norm(ne.type):
                        continue
                    oe_vec = old_vecs.get(_norm(oe.canonical_name))
                    if oe_vec is None:
                        continue
                    sim = _cos_sim(ne_vec, oe_vec)
                    if sim > best_score:
                        best_score = sim
                        best_entity = oe
                if best_entity is not None and best_score >= float(vector_threshold):
                    hit = best_entity
                    score = float(best_score)
                    method = "vector_match"
                elif (
                    best_entity is not None
                    and (float(vector_threshold) - float(vector_uncertain_gap)) <= float(best_score) < float(vector_threshold)
                ):
                    vector_candidate = best_entity
                    score = float(best_score)

            llm_candidate: Optional[GlobalEntityRecord] = None
            if vector_candidate is not None:
                llm_candidate = vector_candidate
                method = "llm_after_vector"
            elif hit is not None and (hit_from_alias or type_conflict or desc_gap >= 3.0):
                llm_candidate = hit
                method = "llm_after_name"

            if hit is None and llm_candidate is not None:
                same, merged, compare_failed = _llm_same_entity_and_merge(incoming=ne, candidate=llm_candidate)
                if compare_failed:
                    llm_compare_failed_count += 1
                if same and merged is not None:
                    hit = merged

            if hit is None:
                hit = GlobalEntityRecord(
                    global_entity_id=self._global_entity_id(group_id=group_id, canonical_name=ne.canonical_name),
                    group_id=group_id,
                    canonical_name=ne.canonical_name,
                    type=ne.type,
                    aliases=sorted({*ne.aliases, ne.canonical_name}),
                    description=ne.description,
                )
                method = "create_global"
            else:
                alias_union = sorted(
                    {
                        hit.canonical_name,
                        ne.canonical_name,
                        *[a for a in hit.aliases if a],
                        *[a for a in ne.aliases if a],
                    }
                )
                hit = GlobalEntityRecord(
                    global_entity_id=hit.global_entity_id or self._global_entity_id(group_id=group_id, canonical_name=hit.canonical_name),
                    group_id=group_id,
                    canonical_name=hit.canonical_name,
                    type=hit.type or ne.type,
                    aliases=alias_union,
                    description=ne.description if len(ne.description or "") > len(hit.description or "") else hit.description,
                )

            global_out[_norm(hit.canonical_name)] = hit
            alias_map[_norm(ne.canonical_name)] = hit.canonical_name
            for a in ne.aliases:
                alias_map[_norm(a)] = hit.canonical_name

            rewritten_entities.append(
                GraphEntityRecord(
                    entity_id=ne.entity_id,
                    group_id=ne.group_id,
                    doc_id=ne.doc_id,
                    canonical_name=hit.canonical_name,
                    type=hit.type or ne.type,
                    aliases=sorted({*ne.aliases, *hit.aliases}),
                    description=ne.description if len(ne.description or "") > len(hit.description or "") else hit.description,
                )
            )
            alignments.append(
                EntityAlignmentRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    local_entity_id=str(uuid5(GRAG_NAMESPACE, f"{group_id}:{doc_id}:{ne.canonical_name}")),
                    global_entity_id=hit.global_entity_id,
                    local_canonical_name=ne.canonical_name,
                    global_canonical_name=hit.canonical_name,
                    alignment_method=method,
                    alignment_score=score,
                )
            )

        def _rewrite(name: str) -> str:
            return alias_map.get(_norm(name), name)

        rewritten_relations = [
            GraphRelationRecord(
                relation_id="",
                group_id=r.group_id,
                doc_id=r.doc_id,
                subject=_rewrite(r.subject),
                object=_rewrite(r.object),
                relation_type=r.relation_type,
                description=r.description,
                confidence=r.confidence,
            )
            for r in relations
        ]
        return list(global_out.values()), alignments, rewritten_entities, rewritten_relations, llm_compare_failed_count

    def _align_relations_to_global(
        self,
        *,
        group_id: str,
        doc_id: str,
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> tuple[List[GlobalRelationRecord], List[RelationAlignmentRecord]]:
        if not relations:
            return [], []

        entity_id_by_name = {
            (e.canonical_name or "").strip().lower(): e.global_entity_id
            for e in global_entities
        }
        existing = {
            (
                r.subject_global_entity_id,
                r.relation_type,
                r.object_global_entity_id,
            ): r
            for r in self._storage.list_group_global_relations(group_id=group_id, limit=5000)
        }

        global_out = dict(existing)
        alignments: List[RelationAlignmentRecord] = []

        for r in relations:
            subj_key = (r.subject or "").strip().lower()
            obj_key = (r.object or "").strip().lower()
            subj_id = entity_id_by_name.get(subj_key)
            obj_id = entity_id_by_name.get(obj_key)
            if not subj_id or not obj_id:
                continue

            key = (subj_id, r.relation_type, obj_id)
            current = global_out.get(key)
            if current is None:
                current = GlobalRelationRecord(
                    global_relation_id=str(uuid5(GRAG_NAMESPACE, f"{group_id}:global_rel:{subj_id}:{r.relation_type}:{obj_id}")),
                    group_id=group_id,
                    subject_global_entity_id=subj_id,
                    subject_name=r.subject,
                    object_global_entity_id=obj_id,
                    object_name=r.object,
                    relation_type=r.relation_type,
                    description=r.description,
                    confidence=r.confidence,
                )
                method = "create_global_relation"
            else:
                current = GlobalRelationRecord(
                    global_relation_id=current.global_relation_id,
                    group_id=group_id,
                    subject_global_entity_id=current.subject_global_entity_id,
                    subject_name=current.subject_name or r.subject,
                    object_global_entity_id=current.object_global_entity_id,
                    object_name=current.object_name or r.object,
                    relation_type=current.relation_type,
                    description=r.description if len(r.description or "") > len(current.description or "") else current.description,
                    confidence=max(
                        [x for x in [current.confidence, r.confidence] if x is not None],
                        default=current.confidence if current.confidence is not None else r.confidence,
                    ),
                )
                method = "merge_global_relation"

            global_out[key] = current
            alignments.append(
                RelationAlignmentRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    local_relation_id=r.relation_id,
                    global_relation_id=current.global_relation_id,
                    subject_name=r.subject,
                    object_name=r.object,
                    relation_type=r.relation_type,
                    alignment_method=method,
                    alignment_score=None,
                )
            )

        return list(global_out.values()), alignments

    def _build_mentions(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
        entities: Sequence[GraphEntityRecord],
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> tuple[List[EntityMentionRecord], List[RelationMentionRecord]]:
        entity_by_name = {(e.canonical_name or "").strip().lower(): e for e in entities}
        global_entity_by_name = {(e.canonical_name or "").strip().lower(): e for e in global_entities}
        relation_by_key = {
            (
                (r.subject or "").strip().lower(),
                r.relation_type,
                (r.object or "").strip().lower(),
            ): r
            for r in relations
        }
        global_relation_by_key = {
            (
                (r.subject_name or "").strip().lower(),
                r.relation_type,
                (r.object_name or "").strip().lower(),
            ): r
            for r in global_relations
        }

        alias_map = {}
        fusion = construction.graph.get("intra_document_fusion") if isinstance(construction.graph, dict) else None
        if fusion is not None:
            alias_map = {
                (str(k or "").strip().lower()): str(v or "").strip()
                for k, v in getattr(fusion, "alias_to_canonical", {}).items()
                if str(k or "").strip() and str(v or "").strip()
            }

        entity_mentions: List[EntityMentionRecord] = []
        relation_mentions: List[RelationMentionRecord] = []

        for chunk in construction.chunks:
            evidence_text = chunk.text[:1000]
            for parsed_entity in chunk.parsed.entities:
                raw_name = (parsed_entity.name or "").strip()
                canonical_name = alias_map.get(raw_name.lower(), raw_name)
                local_entity = entity_by_name.get(canonical_name.lower())
                global_entity = global_entity_by_name.get(canonical_name.lower())
                if local_entity is None or global_entity is None:
                    continue
                mention_id = str(uuid5(GRAG_NAMESPACE, f"ent_mention:{group_id}:{doc_id}:{chunk.chunk_id}:{raw_name}:{parsed_entity.type}"))
                entity_mentions.append(
                    EntityMentionRecord(
                        mention_id=mention_id,
                        group_id=group_id,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        entity_name=raw_name,
                        entity_type=parsed_entity.type,
                        description=parsed_entity.description,
                        evidence_text=evidence_text,
                        local_entity_id=local_entity.entity_id,
                        global_entity_id=global_entity.global_entity_id,
                    )
                )

            for parsed_relation in chunk.parsed.relations:
                raw_subj = (parsed_relation.subject or "").strip()
                raw_obj = (parsed_relation.object or "").strip()
                subj = alias_map.get(raw_subj.lower(), raw_subj)
                obj = alias_map.get(raw_obj.lower(), raw_obj)
                local_relation = relation_by_key.get((subj.lower(), parsed_relation.relation_type, obj.lower()))
                global_relation = global_relation_by_key.get((subj.lower(), parsed_relation.relation_type, obj.lower()))
                if local_relation is None or global_relation is None:
                    continue
                mention_id = str(
                    uuid5(
                        GRAG_NAMESPACE,
                        f"rel_mention:{group_id}:{doc_id}:{chunk.chunk_id}:{raw_subj}:{parsed_relation.relation_type}:{raw_obj}",
                    )
                )
                relation_mentions.append(
                    RelationMentionRecord(
                        mention_id=mention_id,
                        group_id=group_id,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        subject_name=raw_subj,
                        object_name=raw_obj,
                        relation_type=parsed_relation.relation_type,
                        description=parsed_relation.description,
                        evidence_text=evidence_text,
                        local_relation_id=local_relation.relation_id,
                        global_relation_id=global_relation.global_relation_id,
                    )
                )

        return entity_mentions, relation_mentions
