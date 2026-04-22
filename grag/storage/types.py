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
    score: float = 0.0


@dataclass(frozen=True)
class ChunkEmbeddingRecord:
    group_id: str
    doc_id: str
    chunk_id: str
    vector: List[float]


@dataclass(frozen=True)
class GraphChunkCheckpointRecord:
    group_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    status: str
    resolved_text: str
    entity_relation_raw: str
    parsed_json: Dict[str, Any]
    error: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GraphChunkDetailRecord:
    chunk: ChunkRecord
    status: str
    error: str
    updated_at: str
    resolved_text: str
    entity_relation_raw: str
    parsed_json: Dict[str, Any]


@dataclass(frozen=True)
class GraphPipelineCheckpointRecord:
    group_id: str
    doc_id: str
    stage: str
    status: str
    payload_json: Dict[str, Any]
    error: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GraphEntityRecord:
    # entity_id 为“doc 级实体”的稳定 id（uuid5），用于：
    # - 作为 Milvus graph_index 的 source_id
    # - 未来在 Neo4j 中存储/回指实体
    # 说明：
    # - 目前实体节点仍然按 (group_id, doc_id, canonical_name) 作为业务 key
    # - entity_id 主要用于跨系统关联与幂等写入
    entity_id: str
    group_id: str
    doc_id: str
    canonical_name: str
    type: str
    aliases: List[str]
    description: str


@dataclass(frozen=True)
class GraphRelationRecord:
    # relation_id 为“doc 级关系”的稳定 id（uuid5），用于：
    # - 作为 Milvus graph_index 的 source_id
    # - global 检索命中 relation 后，回指到 head/tail 端点并扩图
    relation_id: str
    group_id: str
    doc_id: str
    subject: str
    object: str
    relation_type: str
    description: str
    confidence: Optional[int]


@dataclass(frozen=True)
class GlobalEntityRecord:
    global_entity_id: str
    group_id: str
    canonical_name: str
    type: str
    aliases: List[str]
    description: str


@dataclass(frozen=True)
class EntityAlignmentRecord:
    group_id: str
    doc_id: str
    local_entity_id: str
    global_entity_id: str
    local_canonical_name: str
    global_canonical_name: str
    alignment_method: str
    alignment_score: Optional[float]


@dataclass(frozen=True)
class GlobalRelationRecord:
    global_relation_id: str
    group_id: str
    subject_global_entity_id: str
    subject_name: str
    object_global_entity_id: str
    object_name: str
    relation_type: str
    description: str
    confidence: Optional[int]


@dataclass(frozen=True)
class RelationAlignmentRecord:
    group_id: str
    doc_id: str
    local_relation_id: str
    global_relation_id: str
    subject_name: str
    object_name: str
    relation_type: str
    alignment_method: str
    alignment_score: Optional[float]


@dataclass(frozen=True)
class EntityMentionRecord:
    mention_id: str
    group_id: str
    doc_id: str
    chunk_id: str
    entity_name: str
    entity_type: str
    description: str
    evidence_text: str
    local_entity_id: str
    global_entity_id: str


@dataclass(frozen=True)
class RelationMentionRecord:
    mention_id: str
    group_id: str
    doc_id: str
    chunk_id: str
    subject_name: str
    object_name: str
    relation_type: str
    description: str
    evidence_text: str
    local_relation_id: str
    global_relation_id: str


@dataclass(frozen=True)
class IngestTaskRecord:
    task_id: str
    group_id: str
    doc_id: str
    doc_name: str
    doc_time: str
    status: str
    stage: str
    message: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GraphIndexRecord:
    """写入 Milvus graph_index 的统一 record。

    设计说明：
    - 单 collection + kind 的模式：kind in {"entity", "relation"}
    - source_id:
      - entity: GraphEntityRecord.entity_id
      - relation: GraphRelationRecord.relation_id
    - pk 是 Milvus 的主键（VARCHAR），使用带前缀的稳定字符串，便于 delete/upsert。
    """

    pk: str
    kind: str
    group_id: str
    doc_id: str
    source_id: str
    name: str
    text: str
    embedding: List[float]

    # relation 专用字段（entity 记录会留空字符串即可）
    head_name: str = ""
    tail_name: str = ""
    relation_type: str = ""
