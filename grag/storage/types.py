from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DocumentRecord:
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class ChunkRecord:
    group_id: str
    doc_id: str
    chunk_id: str
    index: int
    text: str


@dataclass(frozen=True)
class ChunkEmbeddingRecord:
    group_id: str
    doc_id: str
    chunk_id: str
    vector: List[float]


@dataclass(frozen=True)
class GraphEntityRecord:
    group_id: str
    doc_id: str
    canonical_name: str
    type: str
    aliases: List[str]
    description: str


@dataclass(frozen=True)
class GraphRelationRecord:
    group_id: str
    doc_id: str
    subject: str
    object: str
    relation_type: str
    description: str
    confidence: Optional[int]
