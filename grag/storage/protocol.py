from __future__ import annotations

from typing import Protocol, Sequence

from .types import (
    ChunkEmbeddingRecord,
    GraphChunkCheckpointRecord,
    GraphPipelineCheckpointRecord,
    ChunkRecord,
    DocumentRecord,
    EntityMentionRecord,
    EntityAlignmentRecord,
    GlobalRelationRecord,
    GraphEntityRecord,
    GraphIndexRecord,
    GraphRelationRecord,
    GlobalEntityRecord,
    IngestTaskRecord,
    RelationMentionRecord,
    RelationAlignmentRecord,
)


class GraphStorage(Protocol):
    def list_doc_chunks(
        self,
        *,
        group_id: str,
        doc_id: str,
        limit: int = 200000,
    ) -> Sequence[ChunkRecord]:
        ...

    def upsert_graph_chunk_checkpoint(self, *, checkpoint: GraphChunkCheckpointRecord) -> None:
        ...

    def list_graph_chunk_checkpoints(
        self,
        *,
        group_id: str,
        doc_id: str,
    ) -> Sequence[GraphChunkCheckpointRecord]:
        ...

    def upsert_graph_pipeline_checkpoint(self, *, checkpoint: GraphPipelineCheckpointRecord) -> None:
        ...

    def list_graph_pipeline_checkpoints(
        self,
        *,
        group_id: str,
        doc_id: str,
    ) -> Sequence[GraphPipelineCheckpointRecord]:
        ...

    def list_group_global_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GlobalEntityRecord]:
        ...

    def list_group_global_relations(self, *, group_id: str, limit: int = 500) -> Sequence[GlobalRelationRecord]:
        ...

    def list_group_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GraphEntityRecord]:
        """列出同一 group 下历史文档中已入库的实体。

        用途：
        - GraphBuilder 在写入新文档前，会用该接口检索历史实体作为候选，进行跨文档 canonical 对齐。

        语义约定（最小可用）：
        - 返回的实体是“doc 级实体”（GraphEntityRecord.doc_id 可能不同），而非全局实体。
        - 调用方只读不写：仅用于本次写入前的决策。
        """
        ...

    def save_base_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
    ) -> None:
        ...

    def save_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
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
        ...

    def save_graph_assets(
        self,
        *,
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
        ...

    def upsert_ingest_task(self, *, task: IngestTaskRecord) -> None:
        ...
