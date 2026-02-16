from __future__ import annotations

from typing import Protocol, Sequence

from .types import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphRelationRecord,
)


class GraphStorage(Protocol):
    def save_document(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        embeddings: Sequence[ChunkEmbeddingRecord],
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> None:
        ...
