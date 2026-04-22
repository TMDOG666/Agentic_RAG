"""grag.storage

存储层（Storage Layer）

职责：
- 定义图谱落库所需的核心数据结构（Document/Chunk/Entity/Relation 等）
- 定义统一的存储接口（storage protocol），供上层流水线调用
- 提供基于 `grag.data_client` 的存储实现

说明：
- 上层（例如 graph_construction）应仅依赖本模块暴露的接口与数据结构，避免直接依赖具体数据库客户端。
"""

from .types import (
    DocumentRecord,
    ChunkRecord,
    ChunkEmbeddingRecord,
    GraphChunkCheckpointRecord,
    GraphPipelineCheckpointRecord,
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
from .protocol import GraphStorage
from .storage_impl import DataClientGraphStorage

__all__ = [
    "DocumentRecord",
    "ChunkRecord",
    "ChunkEmbeddingRecord",
    "GraphChunkCheckpointRecord",
    "GraphPipelineCheckpointRecord",
    "EntityMentionRecord",
    "EntityAlignmentRecord",
    "GlobalRelationRecord",
    "GraphEntityRecord",
    "GraphIndexRecord",
    "GraphRelationRecord",
    "GlobalEntityRecord",
    "IngestTaskRecord",
    "RelationMentionRecord",
    "RelationAlignmentRecord",
    "GraphStorage",
    "DataClientGraphStorage",
]
