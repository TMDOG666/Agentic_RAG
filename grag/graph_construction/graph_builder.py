
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
import math
import json
from uuid import UUID, uuid5
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..model.embedding_client import EmbeddingClient
from ..model.llm_client import LLMClient
from ..storage import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphIndexRecord,
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
        llm_chat_fn: Optional[Callable[[str], str]] = None,
        llm_provider: Optional[str] = None,
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
        self._llm_chat_fn = llm_chat_fn
        self._llm_provider = llm_provider

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
                    # entity_id/relation_id 必须是“融合/重写后的最终结果”才能保持幂等。
                    # 因此这里先占位，稍后统一用 uuid5 生成。
                    entity_id="",
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
                    relation_id="",
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

        # 3.5) 同组多文档融合（跨 doc 的 canonical 对齐）：
        #
        # 背景：
        # - 上游 `GraphConstructionManager` 的 fusion 只做“文档内部”的实体统一。
        # - 但在同一个 group 内，多个文档可能反复出现同一实体（例如同一个人/公司），
        #   需要将“新文档里出现的实体”尽量对齐到“历史文档里已出现的 canonical”。
        #
        # 约束（按当前项目阶段的最小可用实现）：
        # - 只影响当前文档的 `entities/relations`（即：重写本次入库的 canonical 与关系端点）。
        # - 不回写/修改历史 doc 的实体记录（避免跨文档回写导致的幂等/一致性复杂度）。
        #
        # 策略：
        # - 先从存储层读取同 group 的历史实体（由 storage 实现提供，例如从 Postgres grag_entities 读取）。
        # - 关键词/向量召回候选实体。
        # - 只有当“命中但不确定”时才调用 LLM 做同一性判断 + 知识融合（省钱）。
        # - 最终重写 relations 的 subject/object，确保指向融合后的 canonical。
        if entities:
            old_entities = list(self._storage.list_group_entities(group_id=group_id, limit=1000))
            entities, relations = self._cross_document_entity_fusion(
                group_id=group_id,
                new_entities=entities,
                relations=relations,
                old_entities=old_entities,
            )

        # 3.8) 为实体/关系生成“稳定 id”（uuid5）。
        #
        # 说明：
        # - 你要求以 Postgres 的 entity_id/relation_id 作为权威 id。为了让入库幂等且可复现，
        #   我们在写入前统一按确定性规则生成（uuid5）。
        # - 由于 cross-document fusion 可能会改写 canonical_name / subject/object，因此必须在
        #   fusion 完成之后再生成 id。
        GRAG_NAMESPACE = UUID("6b45223b-b3b8-4a2f-b7b7-3d6ad9d2f3f0")

        def _entity_id(e: GraphEntityRecord) -> str:
            return str(uuid5(GRAG_NAMESPACE, f"{e.group_id}:{e.doc_id}:{e.canonical_name}"))

        def _relation_id(r: GraphRelationRecord) -> str:
            return str(uuid5(GRAG_NAMESPACE, f"{r.group_id}:{r.doc_id}:{r.subject}:{r.relation_type}:{r.object}"))

        entities = [
            GraphEntityRecord(
                entity_id=_entity_id(e),
                group_id=e.group_id,
                doc_id=e.doc_id,
                canonical_name=e.canonical_name,
                type=e.type,
                aliases=list(e.aliases),
                description=e.description,
            )
            for e in entities
        ]

        relations = [
            GraphRelationRecord(
                relation_id=_relation_id(r),
                group_id=r.group_id,
                doc_id=r.doc_id,
                subject=r.subject,
                object=r.object,
                relation_type=r.relation_type,
                description=r.description,
                confidence=r.confidence,
            )
            for r in relations
        ]

        # 3.9) 生成 graph_index_records（entity/relation 向量索引）
        #
        # 你确认的模板：
        # - entity: "{canonical_name}\n{aliases}\n{description}"
        # - relation: "{head} -[{type}]-> {tail}\n{description}"
        #
        # 注意：
        # - 这里的 embedding 与 chunk embedding 使用同一个 EmbeddingClient/provider。
        # - 入库策略为“尽快失败”：embedding 失败则整次 build_and_save 失败（与现有 chunk embedding 一致）。
        graph_index_records: List[GraphIndexRecord] = []
        graph_index_texts: List[str] = []
        graph_index_meta: List[tuple[str, object]] = []

        for e in entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            text_for_embedding = f"{e.canonical_name}\n{aliases}\n{e.description}".strip()
            graph_index_texts.append(text_for_embedding)
            graph_index_meta.append(("entity", e))

        for r in relations:
            text_for_embedding = f"{r.subject} -[{r.relation_type}]-> {r.object}\n{r.description}".strip()
            graph_index_texts.append(text_for_embedding)
            graph_index_meta.append(("relation", r))

        if graph_index_texts:
            gi_vectors = self._embedding_client.embed_texts(graph_index_texts)
            for (kind, obj), vec, raw_text in zip(graph_index_meta, gi_vectors, graph_index_texts):
                if kind == "entity":
                    e = obj  # type: ignore[assignment]
                    e_id = getattr(e, "entity_id")
                    graph_index_records.append(
                        GraphIndexRecord(
                            pk=f"e:{e.group_id}:{e.doc_id}:{e_id}",
                            kind="entity",
                            group_id=e.group_id,
                            doc_id=e.doc_id,
                            source_id=e_id,
                            name=e.canonical_name,
                            text=raw_text,
                            embedding=list(vec),
                        )
                    )
                else:
                    r = obj  # type: ignore[assignment]
                    r_id = getattr(r, "relation_id")
                    graph_index_records.append(
                        GraphIndexRecord(
                            pk=f"r:{r.group_id}:{r.doc_id}:{r_id}",
                            kind="relation",
                            group_id=r.group_id,
                            doc_id=r.doc_id,
                            source_id=r_id,
                            name=r.relation_type,
                            text=raw_text,
                            embedding=list(vec),
                            head_name=r.subject,
                            tail_name=r.object,
                            relation_type=r.relation_type,
                        )
                    )

        # 4) 入库
        self._storage.save_document(
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
            graph_index_records=graph_index_records,
        )

        return GraphBuildResult(
            construction=construction,
            document=document,
            chunks=chunks,
            embeddings=embeddings,
            entities=entities,
            relations=relations,
        )

    def _cross_document_entity_fusion(
        self,
        *,
        group_id: str,
        new_entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        old_entities: Sequence[GraphEntityRecord],
        vector_threshold: float = 0.90,
        vector_uncertain_gap: float = 0.05,
    ) -> tuple[List[GraphEntityRecord], List[GraphRelationRecord]]:
        """跨文档实体融合（同 group）。

        输入：
        - new_entities / relations：当前文档（doc_id）内已经做过“文档内部融合”的实体与关系。
        - old_entities：同 group 下历史文档里出现过的 canonical entities（从存储层读取）。

        输出：
        - entities：对齐后的实体列表（仅用于当前文档写入）
        - relations：subject/object 经过 canonical 重写后的关系列表（仅用于当前文档写入）

        重要说明：
        - 本函数不会改写历史文档的实体，也不会在存储层创建“全局实体表”。
        - 这里的“融合”含义是：将当前文档的实体尽量映射到历史 canonical 名称，
          并对 aliases/description 做合并；最终写入仍然是 (group_id, doc_id, canonical_name) 的 doc 级实体。

        触发 LLM（省钱策略）：
        - 仅当候选命中但不确定时调用 LLM。
        - 不确定的定义：
          - 向量相似度落在 [vector_threshold-vector_uncertain_gap, vector_threshold) 区间
          - 或关键词命中但：
            - 命中来自 alias（而不是 canonical 精确命中）
            - 或 type 冲突
            - 或 description 长度差异显著（ratio >= 3）
        """

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        def _entity_text(e: GraphEntityRecord) -> str:
            aliases = " ".join([a for a in e.aliases if a])
            return f"{e.canonical_name}\n{e.type}\n{aliases}\n{e.description}".strip()

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

        def _llm_same_entity_and_merge(
            *,
            incoming: GraphEntityRecord,
            candidate: GraphEntityRecord,
            prefer_canonical: str,
        ) -> Tuple[bool, Optional[GraphEntityRecord]]:
            # LLM 的职责：
            # - 判断 incoming(new) 与 candidate(old) 是否同一实体
            # - 同一时返回合并后的 canonical/aliases/description（尽量沿用 prefer_canonical 以保持稳定）
            #
            # 注意：
            # - 只输出 JSON，方便稳定解析
            # - LLM 输出解析失败时，按“不合并”处理（fail-closed）
            prompt = (
                "你是一个实体对齐与知识融合助手。\n"
                "任务：判断 new_entity 与 old_entity 是否表示同一个现实世界实体。\n"
                "- 如果不是同一个实体：输出 JSON: {\"same\": false}\n"
                "- 如果是同一个实体：输出 JSON: {\"same\": true, \"canonical_name\": <string>, \"type\": <string>, \"aliases\": <list[string]>, \"description\": <string>}\n"
                "要求：\n"
                "- canonical_name 优先使用 prefer_canonical（除非明显更合适）\n"
                "- aliases 需包含两边的 canonical/aliases 并去重\n"
                "- description 融合两边信息，简洁完整\n"
                "只输出 JSON，不要输出其他文字。\n\n"
                f"prefer_canonical: {prefer_canonical}\n"
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
                + "\nold_entity:\n"
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

            chat = self._llm_chat_fn
            if chat is None:
                chat = LLMClient(self._llm_provider).chat

            raw = (chat(prompt) or "").strip()
            try:
                data = json.loads(raw)
            except Exception:
                return False, None

            if not isinstance(data, dict):
                return False, None

            same = bool(data.get("same"))
            if not same:
                return False, None

            canonical_name = str(data.get("canonical_name") or "").strip() or prefer_canonical
            etype = str(data.get("type") or "").strip() or (candidate.type or incoming.type)
            aliases_raw = data.get("aliases")
            desc = str(data.get("description") or "").strip() or (candidate.description or incoming.description)

            aliases: List[str] = []
            if isinstance(aliases_raw, list):
                aliases = [str(x).strip() for x in aliases_raw if str(x).strip()]
            else:
                aliases = []

            return (
                True,
                GraphEntityRecord(
                    # 注意：entity_id 在 build_and_save 的 3.8 阶段统一生成。
                    # 这里先占位，避免 dataclass 缺参，同时保持 fusion 阶段只关注语义字段。
                    entity_id="",
                    group_id=group_id,
                    doc_id=incoming.doc_id,
                    canonical_name=canonical_name,
                    type=etype,
                    aliases=aliases,
                    description=desc,
                ),
            )

        # 1) 关键词检索：按 canonical/alias 精确命中
        #
        # 说明：这里使用“精确命中”是为了快与可解释。
        # - canonical 精确命中：通常认为强信号（更可能同一实体）
        # - alias 命中：可能存在歧义（例如外号/简称/同名），因此可能触发 LLM
        old_by_name: Dict[str, GraphEntityRecord] = {}
        for oe in old_entities:
            old_by_name.setdefault(_norm(oe.canonical_name), oe)
            for a in oe.aliases:
                old_by_name.setdefault(_norm(a), oe)

        # 2) 向量检索：对“实体文本”做 embedding，并在内存中做相似度
        #
        # 说明：为了最小可用实现，这里并未把 entity 向量落 Milvus。
        # - 优点：无需新增 entity collection/schema
        # - 缺点：old_entities 多时会变慢（O(N)），后续可以升级为 entity 向量落库 + ANN 召回。
        old_vecs: Dict[str, List[float]] = {}
        if old_entities:
            old_texts = [_entity_text(e) for e in old_entities]
            if self._embedding_fn is not None:
                provider = self._embedding_provider or "default"
                old_vectors = self._embedding_fn(old_texts, provider)
            else:
                old_vectors = self._embedding_client.embed_texts(old_texts)
            for oe, v in zip(old_entities, old_vectors):
                old_vecs[_norm(oe.canonical_name)] = list(v)

        alias_map: Dict[str, str] = {}
        merged: Dict[str, GraphEntityRecord] = {}

        def _merge_entity(*, base: GraphEntityRecord, incoming: GraphEntityRecord) -> GraphEntityRecord:
            aliases = set([a for a in base.aliases if a] + [a for a in incoming.aliases if a])
            aliases.add(incoming.canonical_name)
            aliases.add(base.canonical_name)
            desc = base.description
            if len((incoming.description or "")) > len((desc or "")):
                desc = incoming.description
            return GraphEntityRecord(
                # 注意：entity_id 在 build_and_save 的 3.8 阶段统一生成。
                entity_id="",
                group_id=group_id,
                doc_id=incoming.doc_id,
                canonical_name=base.canonical_name,
                type=base.type or incoming.type,
                aliases=sorted(aliases),
                description=desc,
            )

        def _desc_gap(a: str, b: str) -> float:
            la = len((a or "").strip())
            lb = len((b or "").strip())
            if la <= 0 and lb <= 0:
                return 0.0
            mn = max(1, min(la, lb))
            mx = max(la, lb)
            return float(mx) / float(mn)

        for ne in new_entities:
            key = _norm(ne.canonical_name)

            keyword_candidate: Optional[GraphEntityRecord] = None
            keyword_hit_from_alias = False
            keyword_type_conflict = False
            keyword_desc_gap = 0.0

            # 2.1 关键词命中
            hit = old_by_name.get(key)
            if hit is None:
                for a in ne.aliases:
                    hit = old_by_name.get(_norm(a))
                    if hit is not None:
                        break

            if hit is not None:
                keyword_candidate = hit
                keyword_hit_from_alias = _norm(hit.canonical_name) != key
                if _norm(hit.type) and _norm(ne.type) and _norm(hit.type) != _norm(ne.type):
                    keyword_type_conflict = True
                keyword_desc_gap = _desc_gap(hit.description, ne.description)

            # 2.2 向量候选（同 type + 高相似度）
            #
            # - 当关键词未命中时，才走向量召回。
            # - 这里对 type 做了“硬过滤”（type 不一致则跳过），用于减少误合并。
            vector_candidate: Optional[GraphEntityRecord] = None
            vector_sim: float = -1.0
            vector_uncertain_candidate: Optional[GraphEntityRecord] = None

            if hit is None and old_entities:
                ne_text = _entity_text(ne)
                if self._embedding_fn is not None:
                    provider = self._embedding_provider or "default"
                    ne_vec = self._embedding_fn([ne_text], provider)[0]
                else:
                    ne_vec = self._embedding_client.embed_texts([ne_text])[0]

                best: tuple[float, Optional[GraphEntityRecord]] = (-1.0, None)
                for oe in old_entities:
                    if _norm(oe.type) and _norm(ne.type) and _norm(oe.type) != _norm(ne.type):
                        continue
                    oe_vec = old_vecs.get(_norm(oe.canonical_name))
                    if oe_vec is None:
                        continue
                    sim = _cos_sim(ne_vec, oe_vec)
                    if sim > best[0]:
                        best = (sim, oe)

                if best[1] is not None and best[0] >= float(vector_threshold):
                    hit = best[1]

                vector_candidate = best[1]
                vector_sim = float(best[0])

                # 不确定区间：命中但不够“明显”，交给 LLM 做判定
                if (
                    best[1] is not None
                    and (float(vector_threshold) - float(vector_uncertain_gap)) <= float(best[0]) < float(vector_threshold)
                ):
                    vector_uncertain_candidate = best[1]

            # 3) 只有“不确定命中”才调用 LLM（省钱）
            # - 向量不确定区间
            # - 关键词命中但：type 冲突 / alias 命中 / 描述差异显著
            keyword_uncertain = (
                keyword_candidate is not None
                and (keyword_type_conflict or keyword_hit_from_alias or keyword_desc_gap >= 3.0)
            )

            llm_candidate: Optional[GraphEntityRecord] = None
            if vector_uncertain_candidate is not None:
                llm_candidate = vector_uncertain_candidate
            elif keyword_uncertain and keyword_candidate is not None:
                llm_candidate = keyword_candidate

            # 3.1 向量/关键词命中但不确定：尝试 LLM 判同 + 产出融合实体
            if hit is None and llm_candidate is not None:
                try:
                    same, merged_llm = _llm_same_entity_and_merge(
                        incoming=ne,
                        candidate=llm_candidate,
                        prefer_canonical=llm_candidate.canonical_name,
                    )
                    if same and merged_llm is not None:
                        merged[_norm(merged_llm.canonical_name)] = merged_llm
                        alias_map[_norm(ne.canonical_name)] = merged_llm.canonical_name
                        for a in ne.aliases:
                            alias_map[_norm(a)] = merged_llm.canonical_name
                        alias_map.setdefault(_norm(llm_candidate.canonical_name), merged_llm.canonical_name)
                        for a in llm_candidate.aliases:
                            alias_map.setdefault(_norm(a), merged_llm.canonical_name)
                        continue
                except Exception:
                    pass

            # 3.2 无命中（或 LLM 判定失败）：保留新实体
            if hit is None:
                merged[key] = ne
                alias_map[_norm(ne.canonical_name)] = ne.canonical_name
                for a in ne.aliases:
                    alias_map[_norm(a)] = ne.canonical_name
                continue

            # 3.3 关键词命中但不确定：交给 LLM 判同+融合（省钱策略下的“必要调用”）
            if keyword_uncertain and keyword_candidate is not None:
                try:
                    same, merged_llm = _llm_same_entity_and_merge(
                        incoming=ne,
                        candidate=keyword_candidate,
                        prefer_canonical=keyword_candidate.canonical_name,
                    )
                    if same and merged_llm is not None:
                        merged[_norm(merged_llm.canonical_name)] = merged_llm
                        alias_map[_norm(ne.canonical_name)] = merged_llm.canonical_name
                        for a in ne.aliases:
                            alias_map[_norm(a)] = merged_llm.canonical_name
                        alias_map.setdefault(_norm(keyword_candidate.canonical_name), merged_llm.canonical_name)
                        for a in keyword_candidate.aliases:
                            alias_map.setdefault(_norm(a), merged_llm.canonical_name)
                        continue
                except Exception:
                    pass

            # 3.4 明显同一实体：启发式合并（不调用 LLM）
            fused = _merge_entity(base=hit, incoming=ne)
            merged[_norm(fused.canonical_name)] = fused
            alias_map[_norm(ne.canonical_name)] = fused.canonical_name
            for a in ne.aliases:
                alias_map[_norm(a)] = fused.canonical_name

            # 将历史实体本身的 canonical/aliases 也纳入映射，便于重写 relations
            alias_map.setdefault(_norm(hit.canonical_name), fused.canonical_name)
            for a in hit.aliases:
                alias_map.setdefault(_norm(a), fused.canonical_name)

        def _rewrite_name(name: str) -> str:
            return alias_map.get(_norm(name), name)

        rewritten_relations: List[GraphRelationRecord] = []
        for r in relations:
            rewritten_relations.append(
                GraphRelationRecord(
                    # 注意：relation_id 在 build_and_save 的 3.8 阶段统一生成。
                    # 这里先占位，避免 dataclass 缺参，同时保持 fusion 阶段只关注语义字段。
                    relation_id="",
                    group_id=r.group_id,
                    doc_id=r.doc_id,
                    subject=_rewrite_name(r.subject),
                    object=_rewrite_name(r.object),
                    relation_type=r.relation_type,
                    description=r.description,
                    confidence=r.confidence,
                )
            )

        return list(merged.values()), rewritten_relations
