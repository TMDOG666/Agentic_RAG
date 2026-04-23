from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .coreference_resolver import DocumentWithCoreferenceResolution
from .entity_relation_parser import ParsedEntityRelation


@dataclass(frozen=True)
class GraphConstructionInput:
    doc_name: str
    doc_time: str
    text: str


@dataclass(frozen=True)
class ChunkExtractionParsed:
    chunk_id: str
    text: str
    resolved_text: str
    entity_relation_raw: str
    parsed: ParsedEntityRelation
    error: Optional[str]


@dataclass(frozen=True)
class GraphConstructionResult:
    doc_name: str
    doc_time: str
    original_text: str
    coreference: DocumentWithCoreferenceResolution
    chunks: List[ChunkExtractionParsed]
    graph: Optional[object]


@dataclass(frozen=True)
class GraphConstructionStreamEvent:
    event_type: str
    stage: str
    doc_id: str
    doc_name: str
    group_id: str
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None
    message: str = ""
    payload: Optional[Dict[str, object]] = None
