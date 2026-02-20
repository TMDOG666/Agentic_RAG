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
    def list_group_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GraphEntityRecord]:
        """列出同一 group 下历史文档中已入库的实体。

        用途：
        - GraphBuilder 在写入新文档前，会用该接口检索历史实体作为候选，进行跨文档 canonical 对齐。

        语义约定（最小可用）：
        - 返回的实体是“doc 级实体”（GraphEntityRecord.doc_id 可能不同），而非全局实体。
        - 调用方只读不写：仅用于本次写入前的决策。
        """
        ...

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
