from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4, uuid5

from ..model.embedding_client import EmbeddingClient
from ..model.llm_client import LLMClient
from ..storage import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    EntityMentionRecord,
    EntityAlignmentRecord,
    GlobalRelationRecord,
    GraphEntityRecord,
    GraphIndexRecord,
    GraphRelationRecord,
    GraphStorage,
    GlobalEntityRecord,
    RelationMentionRecord,
    RelationAlignmentRecord,
)
from .chunker import SemanticChunker
from .graph_construction_manager import GraphConstructionManager, GraphConstructionResult


GRAG_NAMESPACE = UUID("6b45223b-b3b8-4a2f-b7b7-3d6ad9d2f3f0")


@dataclass(frozen=True)
class BaseDocumentBuildResult:
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]


@dataclass(frozen=True)
class GraphBuildResult:
    construction: GraphConstructionResult
    document: DocumentRecord
    chunks: List[ChunkRecord]
    embeddings: List[ChunkEmbeddingRecord]
    entities: List[GraphEntityRecord]
    relations: List[GraphRelationRecord]
    entity_mentions: List[EntityMentionRecord]
    relation_mentions: List[RelationMentionRecord]
    global_entities: List[GlobalEntityRecord]
    entity_alignments: List[EntityAlignmentRecord]
    global_relations: List[GlobalRelationRecord]
    relation_alignments: List[RelationAlignmentRecord]


class GraphBuilder:
    def __init__(
        self,
        *,
        storage: GraphStorage,
        construction_manager: Optional[GraphConstructionManager] = None,
        embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
        embedding_provider: Optional[str] = None,
        llm_chat_fn: Optional[Callable[[str], str]] = None,
        llm_provider: Optional[str] = None,
    ) -> None:
        self._storage = storage
        self._manager = construction_manager or GraphConstructionManager()
        self._embedding_fn = embedding_fn
        self._embedding_provider = embedding_provider
        self._embedding_client = EmbeddingClient(provider_name=embedding_provider)
        self._llm_chat_fn = llm_chat_fn
        self._llm_provider = llm_provider

    def build_base_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> BaseDocumentBuildResult:
        final_doc_id = str(doc_id or uuid4().hex)
        chunk_texts = SemanticChunker().chunk(text)
        chunks = [
            ChunkRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=f"{final_doc_id}::chunk_{i}",
                index=i - 1,
                text=t,
            )
            for i, t in enumerate(chunk_texts, 1)
        ]
        vectors = self._embed_texts([c.text for c in chunks])
        embeddings = [
            ChunkEmbeddingRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=chunks[i].chunk_id,
                vector=vec,
            )
            for i, vec in enumerate(vectors)
        ]
        document = DocumentRecord(
            group_id=group_id,
            doc_id=final_doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            metadata={"original_length": len(text), "ingest_stage": "base_ingested"},
        )
        self._storage.save_base_document(document=document, chunks=chunks, embeddings=embeddings)
        return BaseDocumentBuildResult(document=document, chunks=chunks, embeddings=embeddings)

    def build_graph_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphBuildResult:
        construction = self._manager.run(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
        )
        final_doc_id = self._infer_doc_id(doc_id=doc_id, construction=construction)
        document = DocumentRecord(
            group_id=group_id,
            doc_id=final_doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
            metadata={"original_length": len(text), "ingest_stage": "graph_built"},
        )
        chunks = [
            ChunkRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=c.chunk_id,
                index=i,
                text=c.text,
            )
            for i, c in enumerate(construction.chunks)
        ]
        embeddings = [
            ChunkEmbeddingRecord(
                group_id=group_id,
                doc_id=final_doc_id,
                chunk_id=c.chunk_id,
                vector=vec,
            )
            for c, vec in zip(construction.chunks, self._embed_texts([c.text for c in construction.chunks]))
        ]
        entities, relations = self._build_doc_level_graph_assets(
            construction=construction,
            group_id=group_id,
            doc_id=final_doc_id,
        )
        global_entities, entity_alignments, entities, relations = self._align_entities_to_global(
            group_id=group_id,
            doc_id=final_doc_id,
            new_entities=entities,
            relations=relations,
        )
        entities = [self._with_entity_id(e) for e in entities]
        relations = [self._with_relation_id(r) for r in relations]
        global_relations, relation_alignments = self._align_relations_to_global(
            group_id=group_id,
            doc_id=final_doc_id,
            global_entities=global_entities,
            relations=relations,
        )
        entity_mentions, relation_mentions = self._build_mentions(
            construction=construction,
            group_id=group_id,
            doc_id=final_doc_id,
            entities=entities,
            global_entities=global_entities,
            relations=relations,
            global_relations=global_relations,
        )
        graph_index_records = self._build_graph_index_records(
            entities=entities,
            relations=relations,
            global_entities=global_entities,
            global_relations=global_relations,
        )

        self._storage.save_graph_assets(
            document=document,
            entities=entities,
            relations=relations,
            entity_mentions=entity_mentions,
            relation_mentions=relation_mentions,
            global_entities=global_entities,
            entity_alignments=entity_alignments,
            global_relations=global_relations,
            relation_alignments=relation_alignments,
            graph_index_records=graph_index_records,
        )

        return GraphBuildResult(
            construction=construction,
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
            entity_mentions=entity_mentions,
            relation_mentions=relation_mentions,
            global_entities=global_entities,
            entity_alignments=entity_alignments,
            global_relations=global_relations,
            relation_alignments=relation_alignments,
        )

    def build_and_save(
        self,
        *,
        text: str,
        doc_time: str,
        doc_name: str,
        group_id: str = "default",
        doc_id: Optional[str] = None,
    ) -> GraphBuildResult:
        base = self.build_base_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=doc_id,
        )
        graph = self.build_graph_and_save(
            text=text,
            doc_time=doc_time,
            doc_name=doc_name,
            group_id=group_id,
            doc_id=base.document.doc_id,
        )
        return GraphBuildResult(
            construction=graph.construction,
            document=base.document,
            chunks=base.chunks,
            embeddings=base.embeddings,
            entities=graph.entities,
            relations=graph.relations,
            entity_mentions=graph.entity_mentions,
            relation_mentions=graph.relation_mentions,
            global_entities=graph.global_entities,
            entity_alignments=graph.entity_alignments,
            global_relations=graph.global_relations,
            relation_alignments=graph.relation_alignments,
        )

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._embedding_fn is not None:
            provider = self._embedding_provider or "default"
            return self._embedding_fn(texts, provider)
        return self._embedding_client.embed_texts(texts)

    @staticmethod
    def _infer_doc_id(*, doc_id: Optional[str], construction: GraphConstructionResult) -> str:
        if doc_id:
            return str(doc_id)
        if construction.chunks:
            return str(construction.chunks[0].chunk_id.split("::", 1)[0])
        return "unknown"

    def _build_doc_level_graph_assets(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
    ) -> tuple[List[GraphEntityRecord], List[GraphRelationRecord]]:
        fusion = None
        if construction.graph and isinstance(construction.graph, dict):
            fusion = construction.graph.get("intra_document_fusion")

        entities: List[GraphEntityRecord] = []
        relations: List[GraphRelationRecord] = []
        if fusion is None:
            return entities, relations

        entities = [
            GraphEntityRecord(
                entity_id="",
                group_id=group_id,
                doc_id=doc_id,
                canonical_name=fe.canonical_name,
                type=fe.type,
                aliases=list(fe.aliases),
                description=fe.description,
            )
            for fe in getattr(fusion, "fused_entities", [])
        ]
        relations = [
            GraphRelationRecord(
                relation_id="",
                group_id=group_id,
                doc_id=doc_id,
                subject=r.subject,
                object=r.object,
                relation_type=r.relation_type,
                description=r.description,
                confidence=r.confidence,
            )
            for r in getattr(fusion, "rewritten_relations", [])
        ]
        return entities, relations

    @staticmethod
    def _global_entity_id(*, group_id: str, canonical_name: str) -> str:
        return str(uuid5(GRAG_NAMESPACE, f"{group_id}:global:{canonical_name}"))

    @staticmethod
    def _with_entity_id(e: GraphEntityRecord) -> GraphEntityRecord:
        return GraphEntityRecord(
            entity_id=str(uuid5(GRAG_NAMESPACE, f"{e.group_id}:{e.doc_id}:{e.canonical_name}")),
            group_id=e.group_id,
            doc_id=e.doc_id,
            canonical_name=e.canonical_name,
            type=e.type,
            aliases=list(e.aliases),
            description=e.description,
        )

    @staticmethod
    def _with_relation_id(r: GraphRelationRecord) -> GraphRelationRecord:
        return GraphRelationRecord(
            relation_id=str(uuid5(GRAG_NAMESPACE, f"{r.group_id}:{r.doc_id}:{r.subject}:{r.relation_type}:{r.object}")),
            group_id=r.group_id,
            doc_id=r.doc_id,
            subject=r.subject,
            object=r.object,
            relation_type=r.relation_type,
            description=r.description,
            confidence=r.confidence,
        )

    def _build_graph_index_records(
        self,
        *,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_entities: Sequence[GlobalEntityRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> List[GraphIndexRecord]:
        records: List[GraphIndexRecord] = []
        texts: List[str] = []
        meta: List[tuple[str, object]] = []

        for e in entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            texts.append(f"{e.canonical_name}\n{aliases}\n{e.description}".strip())
            meta.append(("entity", e))
        for r in relations:
            texts.append(f"{r.subject} -[{r.relation_type}]-> {r.object}\n{r.description}".strip())
            meta.append(("relation", r))
        for e in global_entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            texts.append(f"{e.canonical_name}\n{aliases}\n{e.description}".strip())
            meta.append(("global_entity", e))
        for r in global_relations:
            texts.append(f"{r.subject_name} -[{r.relation_type}]-> {r.object_name}\n{r.description}".strip())
            meta.append(("global_relation", r))

        vectors = self._embed_texts(texts) if texts else []
        for (kind, obj), vec, raw_text in zip(meta, vectors, texts):
            if kind == "entity":
                e = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"e:{e.group_id}:{e.doc_id}:{e.entity_id}",
                        kind="entity",
                        group_id=e.group_id,
                        doc_id=e.doc_id,
                        source_id=e.entity_id,
                        name=e.canonical_name,
                        text=raw_text,
                        embedding=list(vec),
                    )
                )
            else:
                if kind == "relation":
                    r = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"r:{r.group_id}:{r.doc_id}:{r.relation_id}",
                            kind="relation",
                            group_id=r.group_id,
                            doc_id=r.doc_id,
                            source_id=r.relation_id,
                            name=r.relation_type,
                            text=raw_text,
                            embedding=list(vec),
                            head_name=r.subject,
                            tail_name=r.object,
                            relation_type=r.relation_type,
                        )
                    )
                elif kind == "global_entity":
                    e = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"e:{e.group_id}:__global__:{e.global_entity_id}",
                            kind="entity",
                            group_id=e.group_id,
                            doc_id="__global__",
                            source_id=e.global_entity_id,
                            name=e.canonical_name,
                            text=raw_text,
                            embedding=list(vec),
                        )
                    )
                else:
                    r = obj  # type: ignore[assignment]
                    records.append(
                        GraphIndexRecord(
                            pk=f"r:{r.group_id}:__global__:{r.global_relation_id}",
                            kind="relation",
                            group_id=r.group_id,
                            doc_id="__global__",
                            source_id=r.global_relation_id,
                            name=r.relation_type,
                            text=raw_text,
                            embedding=list(vec),
                            head_name=r.subject_name,
                            tail_name=r.object_name,
                            relation_type=r.relation_type,
                        )
                    )
        return records

    def _align_entities_to_global(
        self,
        *,
        group_id: str,
        doc_id: str,
        new_entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        vector_threshold: float = 0.90,
        vector_uncertain_gap: float = 0.05,
    ) -> tuple[
        List[GlobalEntityRecord],
        List[EntityAlignmentRecord],
        List[GraphEntityRecord],
        List[GraphRelationRecord],
    ]:
        if not new_entities:
            return [], [], list(new_entities), list(relations)

        old_entities = list(self._storage.list_group_global_entities(group_id=group_id, limit=2000))

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        def _entity_text(name: str, etype: str, aliases: Sequence[str], description: str) -> str:
            return f"{name}\n{etype}\n{' '.join([a for a in aliases if a])}\n{description}".strip()

        def _cos_sim(a: Sequence[float], b: Sequence[float]) -> float:
            if not a or not b or len(a) != len(b):
                return -1.0
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += float(x) * float(y)
                na += float(x) * float(x)
                nb += float(y) * float(y)
            if na <= 0.0 or nb <= 0.0:
                return -1.0
            return dot / (math.sqrt(na) * math.sqrt(nb))

        def _desc_gap(a: str, b: str) -> float:
            la = len((a or "").strip())
            lb = len((b or "").strip())
            if la <= 0 and lb <= 0:
                return 0.0
            return float(max(la, lb)) / float(max(1, min(la, lb)))

        def _llm_same_entity_and_merge(
            *,
            incoming: GraphEntityRecord,
            candidate: GlobalEntityRecord,
        ) -> Tuple[bool, Optional[GlobalEntityRecord]]:
            prompt = (
                "你是实体对齐与知识融合助手。\n"
                "判断 new_entity 与 global_entity 是否是同一真实实体。\n"
                "如果不是，输出 JSON: {\"same\": false}\n"
                "如果是，输出 JSON: "
                "{\"same\": true, \"canonical_name\": <string>, \"type\": <string>, \"aliases\": <list[string]>, \"description\": <string>}\n"
                "只输出 JSON。\n\n"
                "new_entity:\n"
                + json.dumps(
                    {
                        "name": incoming.canonical_name,
                        "type": incoming.type,
                        "aliases": list(incoming.aliases),
                        "description": incoming.description,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + "global_entity:\n"
                + json.dumps(
                    {
                        "name": candidate.canonical_name,
                        "type": candidate.type,
                        "aliases": list(candidate.aliases),
                        "description": candidate.description,
                    },
                    ensure_ascii=False,
                )
            )
            chat = self._llm_chat_fn or LLMClient(self._llm_provider).chat
            raw = (chat(prompt) or "").strip()
            try:
                data = json.loads(raw)
            except Exception:
                return False, None
            if not isinstance(data, dict) or not bool(data.get("same")):
                return False, None
            merged = GlobalEntityRecord(
                global_entity_id=candidate.global_entity_id,
                group_id=group_id,
                canonical_name=str(data.get("canonical_name") or candidate.canonical_name).strip(),
                type=str(data.get("type") or candidate.type).strip(),
                aliases=[
                    str(x).strip()
                    for x in (data.get("aliases") or [])
                    if str(x).strip()
                ],
                description=str(data.get("description") or candidate.description or incoming.description).strip(),
            )
            return True, merged

        old_by_name: Dict[str, GlobalEntityRecord] = {}
        for oe in old_entities:
            old_by_name.setdefault(_norm(oe.canonical_name), oe)
            for a in oe.aliases:
                old_by_name.setdefault(_norm(a), oe)

        old_vecs: Dict[str, List[float]] = {}
        if old_entities:
            old_vectors = self._embed_texts(
                [
                    _entity_text(oe.canonical_name, oe.type, oe.aliases, oe.description)
                    for oe in old_entities
                ]
            )
            for oe, vec in zip(old_entities, old_vectors):
                old_vecs[_norm(oe.canonical_name)] = list(vec)

        global_out: Dict[str, GlobalEntityRecord] = { _norm(e.canonical_name): e for e in old_entities }
        alias_map: Dict[str, str] = {}
        alignments: List[EntityAlignmentRecord] = []
        rewritten_entities: List[GraphEntityRecord] = []

        for ne in new_entities:
            key = _norm(ne.canonical_name)
            hit = old_by_name.get(key)
            hit_from_alias = False
            type_conflict = False
            desc_gap = 0.0
            score: Optional[float] = None
            method = "new_global"

            if hit is None:
                for a in ne.aliases:
                    hit = old_by_name.get(_norm(a))
                    if hit is not None:
                        hit_from_alias = True
                        break

            if hit is not None:
                type_conflict = _norm(hit.type) not in {"", _norm(ne.type)}
                desc_gap = _desc_gap(hit.description, ne.description)
                method = "name_match"

            vector_candidate: Optional[GlobalEntityRecord] = None
            if hit is None and old_entities:
                ne_vec = self._embed_texts(
                    [_entity_text(ne.canonical_name, ne.type, ne.aliases, ne.description)]
                )[0]
                best_score = -1.0
                best_entity: Optional[GlobalEntityRecord] = None
                for oe in old_entities:
                    if _norm(oe.type) and _norm(ne.type) and _norm(oe.type) != _norm(ne.type):
                        continue
                    oe_vec = old_vecs.get(_norm(oe.canonical_name))
                    if oe_vec is None:
                        continue
                    sim = _cos_sim(ne_vec, oe_vec)
                    if sim > best_score:
                        best_score = sim
                        best_entity = oe
                if best_entity is not None and best_score >= float(vector_threshold):
                    hit = best_entity
                    score = float(best_score)
                    method = "vector_match"
                elif (
                    best_entity is not None
                    and (float(vector_threshold) - float(vector_uncertain_gap)) <= float(best_score) < float(vector_threshold)
                ):
                    vector_candidate = best_entity
                    score = float(best_score)

            llm_candidate: Optional[GlobalEntityRecord] = None
            if vector_candidate is not None:
                llm_candidate = vector_candidate
                method = "llm_after_vector"
            elif hit is not None and (hit_from_alias or type_conflict or desc_gap >= 3.0):
                llm_candidate = hit
                method = "llm_after_name"

            if hit is None and llm_candidate is not None:
                same, merged = _llm_same_entity_and_merge(incoming=ne, candidate=llm_candidate)
                if same and merged is not None:
                    hit = merged

            if hit is None:
                hit = GlobalEntityRecord(
                    global_entity_id=self._global_entity_id(group_id=group_id, canonical_name=ne.canonical_name),
                    group_id=group_id,
                    canonical_name=ne.canonical_name,
                    type=ne.type,
                    aliases=sorted({*ne.aliases, ne.canonical_name}),
                    description=ne.description,
                )
                method = "create_global"
            else:
                alias_union = sorted(
                    {
                        hit.canonical_name,
                        ne.canonical_name,
                        *[a for a in hit.aliases if a],
                        *[a for a in ne.aliases if a],
                    }
                )
                hit = GlobalEntityRecord(
                    global_entity_id=hit.global_entity_id or self._global_entity_id(group_id=group_id, canonical_name=hit.canonical_name),
                    group_id=group_id,
                    canonical_name=hit.canonical_name,
                    type=hit.type or ne.type,
                    aliases=alias_union,
                    description=ne.description if len(ne.description or "") > len(hit.description or "") else hit.description,
                )

            global_out[_norm(hit.canonical_name)] = hit
            alias_map[_norm(ne.canonical_name)] = hit.canonical_name
            for a in ne.aliases:
                alias_map[_norm(a)] = hit.canonical_name

            rewritten_entities.append(
                GraphEntityRecord(
                    entity_id=ne.entity_id,
                    group_id=ne.group_id,
                    doc_id=ne.doc_id,
                    canonical_name=hit.canonical_name,
                    type=hit.type or ne.type,
                    aliases=sorted({*ne.aliases, *hit.aliases}),
                    description=ne.description if len(ne.description or "") > len(hit.description or "") else hit.description,
                )
            )
            alignments.append(
                EntityAlignmentRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    local_entity_id=str(uuid5(GRAG_NAMESPACE, f"{group_id}:{doc_id}:{ne.canonical_name}")),
                    global_entity_id=hit.global_entity_id,
                    local_canonical_name=ne.canonical_name,
                    global_canonical_name=hit.canonical_name,
                    alignment_method=method,
                    alignment_score=score,
                )
            )

        def _rewrite(name: str) -> str:
            return alias_map.get(_norm(name), name)

        rewritten_relations = [
            GraphRelationRecord(
                relation_id="",
                group_id=r.group_id,
                doc_id=r.doc_id,
                subject=_rewrite(r.subject),
                object=_rewrite(r.object),
                relation_type=r.relation_type,
                description=r.description,
                confidence=r.confidence,
            )
            for r in relations
        ]
        return list(global_out.values()), alignments, rewritten_entities, rewritten_relations

    def _align_relations_to_global(
        self,
        *,
        group_id: str,
        doc_id: str,
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> tuple[List[GlobalRelationRecord], List[RelationAlignmentRecord]]:
        if not relations:
            return [], []

        entity_id_by_name = {
            (e.canonical_name or "").strip().lower(): e.global_entity_id
            for e in global_entities
        }
        existing = {
            (
                r.subject_global_entity_id,
                r.relation_type,
                r.object_global_entity_id,
            ): r
            for r in self._storage.list_group_global_relations(group_id=group_id, limit=5000)
        }

        global_out = dict(existing)
        alignments: List[RelationAlignmentRecord] = []

        for r in relations:
            subj_key = (r.subject or "").strip().lower()
            obj_key = (r.object or "").strip().lower()
            subj_id = entity_id_by_name.get(subj_key)
            obj_id = entity_id_by_name.get(obj_key)
            if not subj_id or not obj_id:
                continue

            key = (subj_id, r.relation_type, obj_id)
            current = global_out.get(key)
            if current is None:
                current = GlobalRelationRecord(
                    global_relation_id=str(uuid5(GRAG_NAMESPACE, f"{group_id}:global_rel:{subj_id}:{r.relation_type}:{obj_id}")),
                    group_id=group_id,
                    subject_global_entity_id=subj_id,
                    subject_name=r.subject,
                    object_global_entity_id=obj_id,
                    object_name=r.object,
                    relation_type=r.relation_type,
                    description=r.description,
                    confidence=r.confidence,
                )
                method = "create_global_relation"
            else:
                current = GlobalRelationRecord(
                    global_relation_id=current.global_relation_id,
                    group_id=group_id,
                    subject_global_entity_id=current.subject_global_entity_id,
                    subject_name=current.subject_name or r.subject,
                    object_global_entity_id=current.object_global_entity_id,
                    object_name=current.object_name or r.object,
                    relation_type=current.relation_type,
                    description=r.description if len(r.description or "") > len(current.description or "") else current.description,
                    confidence=max(
                        [x for x in [current.confidence, r.confidence] if x is not None],
                        default=current.confidence if current.confidence is not None else r.confidence,
                    ),
                )
                method = "merge_global_relation"

            global_out[key] = current
            alignments.append(
                RelationAlignmentRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    local_relation_id=r.relation_id,
                    global_relation_id=current.global_relation_id,
                    subject_name=r.subject,
                    object_name=r.object,
                    relation_type=r.relation_type,
                    alignment_method=method,
                    alignment_score=None,
                )
            )

        return list(global_out.values()), alignments

    def _build_mentions(
        self,
        *,
        construction: GraphConstructionResult,
        group_id: str,
        doc_id: str,
        entities: Sequence[GraphEntityRecord],
        global_entities: Sequence[GlobalEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_relations: Sequence[GlobalRelationRecord],
    ) -> tuple[List[EntityMentionRecord], List[RelationMentionRecord]]:
        entity_by_name = {(e.canonical_name or "").strip().lower(): e for e in entities}
        global_entity_by_name = {(e.canonical_name or "").strip().lower(): e for e in global_entities}
        relation_by_key = {
            (
                (r.subject or "").strip().lower(),
                r.relation_type,
                (r.object or "").strip().lower(),
            ): r
            for r in relations
        }
        global_relation_by_key = {
            (
                (r.subject_name or "").strip().lower(),
                r.relation_type,
                (r.object_name or "").strip().lower(),
            ): r
            for r in global_relations
        }

        alias_map = {}
        fusion = construction.graph.get("intra_document_fusion") if isinstance(construction.graph, dict) else None
        if fusion is not None:
            alias_map = {
                (str(k or "").strip().lower()): str(v or "").strip()
                for k, v in getattr(fusion, "alias_to_canonical", {}).items()
                if str(k or "").strip() and str(v or "").strip()
            }

        entity_mentions: List[EntityMentionRecord] = []
        relation_mentions: List[RelationMentionRecord] = []

        for chunk in construction.chunks:
            evidence_text = chunk.text[:1000]
            for parsed_entity in chunk.parsed.entities:
                raw_name = (parsed_entity.name or "").strip()
                canonical_name = alias_map.get(raw_name.lower(), raw_name)
                local_entity = entity_by_name.get(canonical_name.lower())
                global_entity = global_entity_by_name.get(canonical_name.lower())
                if local_entity is None or global_entity is None:
                    continue
                mention_id = str(uuid5(GRAG_NAMESPACE, f"ent_mention:{group_id}:{doc_id}:{chunk.chunk_id}:{raw_name}:{parsed_entity.type}"))
                entity_mentions.append(
                    EntityMentionRecord(
                        mention_id=mention_id,
                        group_id=group_id,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        entity_name=raw_name,
                        entity_type=parsed_entity.type,
                        description=parsed_entity.description,
                        evidence_text=evidence_text,
                        local_entity_id=local_entity.entity_id,
                        global_entity_id=global_entity.global_entity_id,
                    )
                )

            for parsed_relation in chunk.parsed.relations:
                raw_subj = (parsed_relation.subject or "").strip()
                raw_obj = (parsed_relation.object or "").strip()
                subj = alias_map.get(raw_subj.lower(), raw_subj)
                obj = alias_map.get(raw_obj.lower(), raw_obj)
                local_relation = relation_by_key.get((subj.lower(), parsed_relation.relation_type, obj.lower()))
                global_relation = global_relation_by_key.get((subj.lower(), parsed_relation.relation_type, obj.lower()))
                if local_relation is None or global_relation is None:
                    continue
                mention_id = str(
                    uuid5(
                        GRAG_NAMESPACE,
                        f"rel_mention:{group_id}:{doc_id}:{chunk.chunk_id}:{raw_subj}:{parsed_relation.relation_type}:{raw_obj}",
                    )
                )
                relation_mentions.append(
                    RelationMentionRecord(
                        mention_id=mention_id,
                        group_id=group_id,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        subject_name=raw_subj,
                        object_name=raw_obj,
                        relation_type=parsed_relation.relation_type,
                        description=parsed_relation.description,
                        evidence_text=evidence_text,
                        local_relation_id=local_relation.relation_id,
                        global_relation_id=global_relation.global_relation_id,
                    )
                )

        return entity_mentions, relation_mentions
