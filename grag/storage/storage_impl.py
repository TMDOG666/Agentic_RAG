from __future__ import annotations

from typing import Optional, Sequence

from grag.data_client import DataManager, get_data_manager

from .protocol import GraphStorage
from .types import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphRelationRecord,
)


class DataClientGraphStorage(GraphStorage):
    def __init__(self, *, data_manager: Optional[DataManager] = None) -> None:
        self._data_manager = data_manager or get_data_manager()

    def save_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> None:
        pg = self._data_manager.get_postgres_client()
        milvus = self._data_manager.get_milvus_client()
        neo4j = self._data_manager.get_neo4j_client()

        saver_pg = getattr(pg, "save_document", None)
        if callable(saver_pg):
            saver_pg(document=document, chunks=chunks, entities=entities)

        saver_milvus = getattr(milvus, "save_embeddings", None)
        if callable(saver_milvus):
            saver_milvus(document=document, embeddings=embeddings)

        saver_neo4j = getattr(neo4j, "save_graph", None)
        if callable(saver_neo4j):
            saver_neo4j(document=document, entities=entities, relations=relations)
