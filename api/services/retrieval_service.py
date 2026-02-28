from __future__ import annotations

"""api.services.retrieval_service

RetrievalService：检索业务层。

定位：
- 将 API 层的 `RetrievalRequest` 翻译成对 `grag.entrypoint.GRAG` 的具体方法调用。
- 将返回结果统一封装成 `RetrievalResponse(result=...)`，方便前端消费。

说明：
- `GRAG` 内部会创建/复用 RetrievalManager。
- 不同 mode 的返回结构不同：
  - chunks_*: 返回 RetrievalResult dataclass（包含 hits + graph）
  - entities/relations: 返回 list[dict]
  - relations_by_entities/entities_by_relations: 返回 list[dict]
"""

from dataclasses import asdict

from grag.entrypoint import GRAG

from api.schemas.retrieval import RetrievalRequest, RetrievalResponse


class RetrievalService:
    """检索服务。"""

    def __init__(self) -> None:
        # GRAG facade：提供 chunks_vector/chunks_keyword/entities/relations 等统一入口。
        self._grag = GRAG()

    def retrieve(self, payload: RetrievalRequest) -> RetrievalResponse:
        """按 mode 分发检索请求。"""
        mode = payload.mode

        if mode == "chunks_vector":
            # 语义向量召回 chunks（Milvus ANN + 回源 Postgres chunk 文本）。
            r = self._grag.chunks_vector(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                doc_time_start=payload.doc_time_start,
                doc_time_end=payload.doc_time_end,
                rerank_enabled=payload.rerank_enabled,
                rerank_provider=payload.rerank_provider,
            )
            return RetrievalResponse(result=_retrieval_result_to_dict(r))

        if mode == "chunks_keyword":
            # 关键词召回 chunks（Postgres ILIKE）。
            r = self._grag.chunks_keyword(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                doc_time_start=payload.doc_time_start,
                doc_time_end=payload.doc_time_end,
                rerank_enabled=payload.rerank_enabled,
                rerank_provider=payload.rerank_provider,
            )
            return RetrievalResponse(result=_retrieval_result_to_dict(r))

        if mode == "entities":
            # graph_index(kind=entity) 向量召回实体。
            r = self._grag.entities(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                output_fields=payload.output_fields,
            )
            return RetrievalResponse(result={"entities": list(r or [])})

        if mode == "relations":
            # graph_index(kind=relation) 向量召回关系三元组候选。
            r = self._grag.relations(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                output_fields=payload.output_fields,
            )
            return RetrievalResponse(result={"relations": list(r or [])})

        if mode == "relations_by_entities":
            # Neo4j 扩展：给定实体名列表，查 1-hop 关系。
            r = self._grag.relations_by_entities(
                group_id=payload.group_id,
                entity_names=list(payload.entity_names or []),
                limit=int(payload.limit or 200),
                doc_id=payload.doc_id,
            )
            return RetrievalResponse(result={"relations": list(r or [])})

        if mode == "entities_by_relations":
            # Neo4j 扩展：给定 relation_id 或三元组，回查连接的实体。
            r = self._grag.entities_by_relations(
                group_id=payload.group_id,
                relation_ids=list(payload.relation_ids or []) if payload.relation_ids is not None else None,
                relation_triples=list(payload.relation_triples or []) if payload.relation_triples is not None else None,
                limit=int(payload.limit or 200),
                doc_id=payload.doc_id,
            )
            return RetrievalResponse(result={"entities": list(r or [])})

        raise ValueError(f"unsupported mode: {mode}")


def _retrieval_result_to_dict(r) -> dict:
    """将 RetrievalResult（dataclass）转换为普通 dict。

    说明：
    - FastAPI/Pydantic 更适合返回标准 JSON 结构。
    - asdict 会递归处理 dataclass 字段（hit/graph 等）。
    """

    # RetrievalResult is a dataclass; nested hits are also dataclasses.
    try:
        d = asdict(r)
    except Exception:
        # 防御式：一旦结构不符合预期，返回空结构而不是直接 500。
        d = {"keyword_hits": [], "semantic_hits": [], "graph": None}

    # graph sub-results may be dataclasses too.
    g = d.get("graph")
    if g is not None and not isinstance(g, dict):
        try:
            d["graph"] = asdict(g)
        except Exception:
            d["graph"] = None
    return d
