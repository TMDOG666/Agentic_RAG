from __future__ import annotations

from typing import Optional, Sequence

from grag.config import get_config_manager
from grag.data_client import DataManager, get_data_manager

from .protocol import GraphStorage
from .repositories import (
    MilvusGraphIndexRepository,
    MilvusVectorRepository,
    Neo4jGraphRepository,
    PostgresGraphRepository,
)
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


class DataClientGraphStorage(GraphStorage):
    def __init__(
        self,
        *,
        data_manager: Optional[DataManager] = None,
        milvus_collection_name: Optional[str] = None,
        milvus_graph_index_collection_name: Optional[str] = None,
        milvus_upsert_strategy: str = "insert_only",
    ) -> None:
        self._data_manager = data_manager or get_data_manager()
        settings = get_config_manager().get_settings()
        self._pg_repo = PostgresGraphRepository(self._data_manager.get_postgres_client())
        self._milvus_repo = MilvusVectorRepository(
            self._data_manager.get_milvus_client(),
            collection_name=milvus_collection_name,
            upsert_strategy=milvus_upsert_strategy,
        )
        self._graph_index_repo = MilvusGraphIndexRepository(
            self._data_manager.get_milvus_client(),
            collection_name=str(
                milvus_graph_index_collection_name
                or settings.get_default_graph_index_collection_name()
            ),
            upsert_strategy=milvus_upsert_strategy,
        )
        self._neo4j_repo = Neo4jGraphRepository(self._data_manager.get_neo4j_client())

    def save_base_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
    ) -> None:
        self._pg_repo.upsert_document_and_chunks(
            document=document,
            chunks=chunks,
            entities=[],
            relations=[],
        )
        self._milvus_repo.upsert_chunk_embeddings(document=document, embeddings=embeddings)

    def list_doc_chunks(
        self,
        *,
        group_id: str,
        doc_id: str,
        limit: int = 200000,
    ) -> Sequence[ChunkRecord]:
        return self._pg_repo.list_doc_chunks(group_id=group_id, doc_id=doc_id, limit=limit)

    def upsert_graph_chunk_checkpoint(self, *, checkpoint: GraphChunkCheckpointRecord) -> None:
        self._pg_repo.upsert_graph_chunk_checkpoint(checkpoint=checkpoint)

    def list_graph_chunk_checkpoints(
        self,
        *,
        group_id: str,
        doc_id: str,
    ) -> Sequence[GraphChunkCheckpointRecord]:
        return self._pg_repo.list_graph_chunk_checkpoints(group_id=group_id, doc_id=doc_id)

    def upsert_graph_pipeline_checkpoint(self, *, checkpoint: GraphPipelineCheckpointRecord) -> None:
        self._pg_repo.upsert_graph_pipeline_checkpoint(checkpoint=checkpoint)

    def list_graph_pipeline_checkpoints(
        self,
        *,
        group_id: str,
        doc_id: str,
    ) -> Sequence[GraphPipelineCheckpointRecord]:
        return self._pg_repo.list_graph_pipeline_checkpoints(group_id=group_id, doc_id=doc_id)

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
        self._pg_repo.upsert_document_and_chunks(
            document=document,
            chunks=[],
            entities=entities,
            relations=relations,
        )
        self._pg_repo.upsert_entity_mentions(mentions=entity_mentions)
        self._pg_repo.upsert_relation_mentions(mentions=relation_mentions)
        self._pg_repo.upsert_global_entities(entities=global_entities)
        self._pg_repo.upsert_entity_alignments(alignments=entity_alignments)
        self._pg_repo.upsert_global_relations(relations=global_relations)
        self._pg_repo.upsert_relation_alignments(alignments=relation_alignments)
        self._graph_index_repo.upsert_records(records=graph_index_records)
        self._neo4j_repo.upsert_graph(
            document=document,
            entities=entities,
            relations=relations,
            global_entities=global_entities,
            global_relations=global_relations,
        )

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
        self.save_base_document(document=document, chunks=chunks, embeddings=embeddings)
        self.save_graph_assets(
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

    def list_group_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GraphEntityRecord]:
        return self._pg_repo.list_group_entities(group_id=group_id, limit=limit)

    def list_group_global_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GlobalEntityRecord]:
        return self._pg_repo.list_group_global_entities(group_id=group_id, limit=limit)

    def list_group_global_relations(self, *, group_id: str, limit: int = 500) -> Sequence[GlobalRelationRecord]:
        return self._pg_repo.list_group_global_relations(group_id=group_id, limit=limit)

    def upsert_ingest_task(self, *, task: IngestTaskRecord) -> None:
        self._pg_repo.upsert_ingest_task(task=task)
