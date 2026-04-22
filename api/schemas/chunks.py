from __future__ import annotations

from pydantic import BaseModel

from grag.storage.types import ChunkRecord


class ChunkOut(BaseModel):
    group_id: str
    doc_id: str
    chunk_id: str
    index: int
    text: str
    score: float = 0.0
    status: str = "pending"
    error: str = ""
    updated_at: str = ""
    resolved_text: str = ""
    entity_relation_raw: str = ""
    parsed_entities: list[dict] = []
    parsed_relations: list[dict] = []
    parse_errors: list[str] = []

    @staticmethod
    def from_chunk_record(
        chunk: ChunkRecord,
        *,
        status: str = "pending",
        error: str = "",
        updated_at: str = "",
        resolved_text: str = "",
        entity_relation_raw: str = "",
        parsed_entities: list[dict] | None = None,
        parsed_relations: list[dict] | None = None,
        parse_errors: list[str] | None = None,
    ) -> "ChunkOut":
        return ChunkOut(
            group_id=str(chunk.group_id),
            doc_id=str(chunk.doc_id),
            chunk_id=str(chunk.chunk_id),
            index=int(chunk.index),
            text=str(chunk.text),
            score=float(chunk.score or 0.0),
            status=str(status or "pending"),
            error=str(error or ""),
            updated_at=str(updated_at or ""),
            resolved_text=str(resolved_text or ""),
            entity_relation_raw=str(entity_relation_raw or ""),
            parsed_entities=list(parsed_entities or []),
            parsed_relations=list(parsed_relations or []),
            parse_errors=[str(item) for item in (parse_errors or [])],
        )
