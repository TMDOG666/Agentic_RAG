
"""grag.graph_construction.graph_builder

图资产构建器（Builder）。

单一职责：
- 将 `GraphConstructionManager` 产出的“流程结果”（coref/chunks/fusion 等）转换为
  可持久化的存储数据结构（Document/Chunk/Embedding/Entity/Relation）。
- 调用 `grag.storage.GraphStorage` 将数据落库。

与 `GraphConstructionManager` 的职责边界：
- manager：只串联流程，不做 embedding，不做落库。
- builder：负责 embedding + 资产结构化 + 调用 storage。

说明：
- 这里的 embedding 以 chunk 维度为主（ChunkEmbeddingRecord），用于向量检索/GraphRAG。
- 实体融合（canonical entity）与关系重写（rewritten relations）来自 manager 内的 fusion 结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from ..model.embedding_client import EmbeddingClient
from ..storage import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphRelationRecord,
    GraphStorage,
)

from .graph_construction_manager import GraphConstructionManager, GraphConstructionResult


@dataclass(frozen=True)
class GraphBuildResult:
    """GraphBuilder 的返回结果。

    之所以单独定义，是为了：
    - 上层可同时获得“流程结果”（便于调试/可观测）
    - 以及“入库资产”（便于测试/校验落库内容）
    """

    construction: GraphConstructionResult
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]
    entities: List[GraphEntityRecord]
    relations: List[GraphRelationRecord]


class GraphBuilder:
    def __init__(
        self,
        *,
        storage: GraphStorage,
        construction_manager: Optional[GraphConstructionManager] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
        embedding_provider: Optional[str] = None,
    ) -> None:
        """创建 GraphBuilder。

        Args:
            storage:
                存储接口实现（例如 DataClientGraphStorage 或测试用 FakeStorage）。
                GraphBuilder 只依赖接口，不依赖具体数据库客户端。

            construction_manager:
                流程编排器。默认会创建一个 GraphConstructionManager。

            embedding_fn / embedding_provider:
                用于 chunk embedding 的依赖注入。
                - 传 embedding_fn：一般用于测试（避免真实 embedding 调用）
                - 不传 embedding_fn：使用 EmbeddingClient(provider_name=embedding_provider)
        """

        self._storage = storage
        self._manager = construction_manager or GraphConstructionManager()
        self._embedding_fn = embedding_fn
        self._embedding_provider = embedding_provider
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)

    def build_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphBuildResult:
        """执行“构建 + 落库”。

        步骤：
        1. 调用 GraphConstructionManager 串联流程，得到结构化结果（含融合后的实体/关系）
        2. 对 chunks 计算 embedding
        3. 构造 storage records
        4. 调用 storage.save_document 入库
        """

        # 1) 流程串联（manager 不做 embedding/落库）
        construction = self._manager.run(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
        )

        # doc_id 如果未传，会由 manager 生成，并体现在 chunk_id 前缀中。
        # 这里取 doc_id 的“最终值”用于落库主键。
        final_doc_id = doc_id
        if final_doc_id is None and construction.chunks:
            # chunk_id 格式："{doc_id}::chunk_{i}"，因此可以从第一个 chunk 推断 doc_id。
            final_doc_id = construction.chunks[0].chunk_id.split("::", 1)[0]
        if final_doc_id is None:
            # 极端情况：文本为空导致无 chunk。此时给出一个可追踪的 doc_id。
            # （保持与 manager 内部 uuid 生成逻辑一致即可）
            final_doc_id = "unknown"

        # 2) chunk embedding（chunk 文本来自解析结果；保持与后续入库的 chunk_id 对齐）
        chunk_texts = [c.text for c in construction.chunks]
        vectors: List[List[float]]
        if self._embedding_fn is not None:
            provider = self._embedding_provider or "default"
            vectors = self._embedding_fn(chunk_texts, provider)
        else:
            vectors = self._embedding_client.embed_texts(chunk_texts)

        # 3) 构造 records
        document = DocumentRecord(
            group_id=group_id,
            doc_id=str(final_doc_id),
            doc_name=doc_name,
            doc_time=doc_time,
            metadata={"original_length": len(text)},
        )

        chunks = [
            ChunkRecord(
                group_id=group_id,
                doc_id=str(final_doc_id),
                chunk_id=c.chunk_id,
                index=i,
                text=c.text,
            )
            for i, c in enumerate(construction.chunks)
        ]

        embeddings = [
            ChunkEmbeddingRecord(
                group_id=group_id,
                doc_id=str(final_doc_id),
                chunk_id=construction.chunks[i].chunk_id,
                vector=vec,
            )
            for i, vec in enumerate(vectors)
        ]

        fusion = None
        if construction.graph and isinstance(construction.graph, dict):
            fusion = construction.graph.get("intra_document_fusion")

        entities: List[GraphEntityRecord] = []
        relations: List[GraphRelationRecord] = []
        if fusion is not None:
            # 融合结果来自 entity_resolution_knowledge_fusion.IntraDocumentFusionResult
            entities = [
                GraphEntityRecord(
                    group_id=group_id,
                    doc_id=str(final_doc_id),
                    canonical_name=fe.canonical_name,
                    type=fe.type,
                    aliases=list(fe.aliases),
                    description=fe.description,
                )
                for fe in getattr(fusion, "fused_entities", [])
            ]

            relations = [
                GraphRelationRecord(
                    group_id=group_id,
                    doc_id=str(final_doc_id),
                    subject=r.subject,
                    object=r.object,
                    relation_type=r.relation_type,
                    description=r.description,
                    confidence=r.confidence,
                )
                for r in getattr(fusion, "rewritten_relations", [])
            ]

        # 4) 入库
        self._storage.save_document(
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
        )

        return GraphBuildResult(
            construction=construction,
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
        )
