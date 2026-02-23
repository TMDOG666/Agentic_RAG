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
