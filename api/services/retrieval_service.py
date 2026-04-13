from __future__ import annotations

from dataclasses import asdict

from grag.data_client import get_data_manager
from grag.entrypoint import GRAG
from grag.storage.repositories.postgres_repository import PostgresGraphRepository

from api.schemas.retrieval import RetrievalRequest, RetrievalResponse


class RetrievalService:
    def __init__(self) -> None:
        self._grag = GRAG()
        dm = get_data_manager()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())

    def retrieve(self, payload: RetrievalRequest) -> RetrievalResponse:
        mode = payload.mode
        include_evidence = bool(payload.include_evidence)

        if mode == "chunks_vector":
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
            result = _retrieval_result_to_dict(r)
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.top_k,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "chunks_keyword":
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
            result = _retrieval_result_to_dict(r)
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.top_k,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "entities":
            hits = self._grag.entities(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                output_fields=payload.output_fields,
            )
            if include_evidence:
                result = {
                    "entities": list(hits or []),
                    "evidence": self._entity_evidence(
                        group_id=payload.group_id,
                        hits=list(hits or []),
                        doc_id=payload.doc_id,
                    ),
                }
                result["meta"] = self._build_result_meta(
                    mode=mode,
                    query=payload.query,
                    top_k=payload.top_k,
                    result=result,
                )
                return RetrievalResponse(result=result)
            result = {"entities": list(hits or [])}
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.top_k,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "relations":
            hits = self._grag.relations(
                group_id=payload.group_id,
                query=payload.query or "",
                top_k=int(payload.top_k or 20),
                doc_id=payload.doc_id,
                output_fields=payload.output_fields,
            )
            if include_evidence:
                result = {
                    "relations": list(hits or []),
                    "evidence": self._relation_evidence(
                        group_id=payload.group_id,
                        hits=list(hits or []),
                        doc_id=payload.doc_id,
                    ),
                }
                result["meta"] = self._build_result_meta(
                    mode=mode,
                    query=payload.query,
                    top_k=payload.top_k,
                    result=result,
                )
                return RetrievalResponse(result=result)
            result = {"relations": list(hits or [])}
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.top_k,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "graph_search":
            entity_hits = list(
                self._grag.entities(
                    group_id=payload.group_id,
                    query=payload.query or "",
                    top_k=int(payload.top_k or 10),
                    doc_id=payload.doc_id,
                    output_fields=payload.output_fields,
                )
                or []
            )
            relation_hits = list(
                self._grag.relations(
                    group_id=payload.group_id,
                    query=payload.query or "",
                    top_k=int(payload.top_k or 10),
                    doc_id=payload.doc_id,
                    output_fields=payload.output_fields,
                )
                or []
            )
            entity_names = self._pick_entity_names(entity_hits, relation_hits)
            graph_relations = self._grag.relations_by_entities(
                group_id=payload.group_id,
                entity_names=entity_names,
                limit=int(payload.limit or 100),
                doc_id=payload.doc_id,
            ) if entity_names else []
            graph_entities = self._grag.entities_by_relations(
                group_id=payload.group_id,
                relation_ids=[str(r.get("relation_id") or r.get("source_id") or "").strip() for r in graph_relations if str(r.get("relation_id") or r.get("source_id") or "").strip()],
                relation_triples=[
                    {
                        "head_name": r.get("head_name"),
                        "tail_name": r.get("tail_name"),
                        "relation_type": r.get("relation_type") or r.get("type"),
                    }
                    for r in graph_relations
                ],
                limit=int(payload.limit or 100),
                doc_id=payload.doc_id,
            ) if graph_relations else []

            result = {
                "entities": entity_hits,
                "relations": relation_hits,
                "graph": {
                    "entity_names": entity_names,
                    "relations": list(graph_relations or []),
                    "entities": list(graph_entities or []),
                },
            }
            if include_evidence:
                result["evidence"] = {
                    "entities": self._entity_evidence(group_id=payload.group_id, hits=entity_hits, doc_id=payload.doc_id),
                    "relations": self._relation_evidence(group_id=payload.group_id, hits=relation_hits, doc_id=payload.doc_id),
                }
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.top_k,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "relations_by_entities":
            r = self._grag.relations_by_entities(
                group_id=payload.group_id,
                entity_names=list(payload.entity_names or []),
                limit=int(payload.limit or 200),
                doc_id=payload.doc_id,
            )
            result = {"relations": list(r or [])}
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.limit,
                result=result,
            )
            return RetrievalResponse(result=result)

        if mode == "entities_by_relations":
            r = self._grag.entities_by_relations(
                group_id=payload.group_id,
                relation_ids=list(payload.relation_ids or []) if payload.relation_ids is not None else None,
                relation_triples=list(payload.relation_triples or []) if payload.relation_triples is not None else None,
                limit=int(payload.limit or 200),
                doc_id=payload.doc_id,
            )
            result = {"entities": list(r or [])}
            result["meta"] = self._build_result_meta(
                mode=mode,
                query=payload.query,
                top_k=payload.limit,
                result=result,
            )
            return RetrievalResponse(result=result)

        raise ValueError(f"unsupported mode: {mode}")

    @staticmethod
    def _pick_entity_names(entity_hits: list[dict], relation_hits: list[dict], limit: int = 8) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for hit in entity_hits:
            name = str(hit.get("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
                if len(out) >= limit:
                    return out
        for hit in relation_hits:
            for key in ("head_name", "tail_name"):
                name = str(hit.get(key) or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    out.append(name)
                    if len(out) >= limit:
                        return out
        return out

    @staticmethod
    def _build_result_meta(*, mode: str, query: str | None, top_k: int | None, result: dict) -> dict:
        counts: dict[str, int] = {}
        source_modes: list[str] = []
        for key in ("keyword_hits", "semantic_hits", "entities", "relations"):
            value = result.get(key)
            if isinstance(value, list):
                counts[key] = len(value)
                if value:
                    source_modes.append(key)

        graph = result.get("graph")
        if isinstance(graph, dict):
            graph_counts = {
                "entity_names": len(graph.get("entity_names") or []),
                "graph_relations": len(graph.get("relations") or []),
                "graph_entities": len(graph.get("entities") or []),
            }
            counts.update(graph_counts)
            if graph_counts["graph_relations"] or graph_counts["graph_entities"]:
                source_modes.append("graph")

        return {
            "mode": str(mode or ""),
            "query": str(query or ""),
            "requested_top_k": int(top_k) if top_k is not None else None,
            "counts": counts,
            "source_modes": source_modes,
            "has_evidence": "evidence" in result,
        }

    def _entity_evidence(self, *, group_id: str, hits: list[dict], doc_id: str | None) -> dict:
        global_ids: list[str] = []
        local_ids: list[str] = []
        for h in hits:
            source_id = str(h.get("source_id") or "").strip()
            hit_doc_id = str(h.get("doc_id") or "").strip()
            if not source_id:
                continue
            if hit_doc_id == "__global__":
                global_ids.append(source_id)
            else:
                local_ids.append(source_id)

        mentions = self._pg.list_entity_mentions(
            group_id=group_id,
            global_entity_ids=global_ids,
            local_entity_ids=local_ids,
            doc_id=doc_id,
            limit=300,
        )
        chunk_ids = list({m.chunk_id for m in mentions})
        chunks = self._pg.get_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        chunks_by_id = {
            c.chunk_id: {
                "group_id": c.group_id,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "index": c.index,
                "text": c.text,
            }
            for c in chunks
        }
        return {
            "entity_mentions": [asdict(m) for m in mentions],
            "chunks": [chunks_by_id[cid] for cid in chunk_ids if cid in chunks_by_id],
        }

    def _relation_evidence(self, *, group_id: str, hits: list[dict], doc_id: str | None) -> dict:
        global_ids: list[str] = []
        local_ids: list[str] = []
        for h in hits:
            source_id = str(h.get("source_id") or "").strip()
            hit_doc_id = str(h.get("doc_id") or "").strip()
            if not source_id:
                continue
            if hit_doc_id == "__global__":
                global_ids.append(source_id)
            else:
                local_ids.append(source_id)

        mentions = self._pg.list_relation_mentions(
            group_id=group_id,
            global_relation_ids=global_ids,
            local_relation_ids=local_ids,
            doc_id=doc_id,
            limit=300,
        )
        chunk_ids = list({m.chunk_id for m in mentions})
        chunks = self._pg.get_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        chunks_by_id = {
            c.chunk_id: {
                "group_id": c.group_id,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "index": c.index,
                "text": c.text,
            }
            for c in chunks
        }
        return {
            "relation_mentions": [asdict(m) for m in mentions],
            "chunks": [chunks_by_id[cid] for cid in chunk_ids if cid in chunks_by_id],
        }


def _retrieval_result_to_dict(r) -> dict:
    try:
        d = asdict(r)
    except Exception:
        try:
            d = {
                "keyword_hits": [
                    asdict(x) if hasattr(x, "__dataclass_fields__") else dict(vars(x))
                    for x in list(getattr(r, "keyword_hits", []) or [])
                ],
                "semantic_hits": [
                    asdict(x) if hasattr(x, "__dataclass_fields__") else dict(vars(x))
                    for x in list(getattr(r, "semantic_hits", []) or [])
                ],
                "graph": getattr(r, "graph", None),
                "local_graph": getattr(r, "local_graph", None),
                "global_graph": getattr(r, "global_graph", None),
            }
        except Exception:
            d = {"keyword_hits": [], "semantic_hits": [], "graph": None}
    g = d.get("graph")
    if g is not None and not isinstance(g, dict):
        try:
            d["graph"] = asdict(g)
        except Exception:
            d["graph"] = None
    return d
