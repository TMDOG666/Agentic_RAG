# Graph Builder Module

"""grag.graph_construction.entity_resolution_knowledge_fusion

文档内部的实体统一（Entity Resolution）与知识融合（Knowledge Fusion）。

本模块实现“文档内部处理 (Intra-Document)”第 1-6 步（不包含第 7 步全局入库）：

1) 收集所有 chunk 的实体/关系（输入为解析后的结构化对象）
2) 对实体做向量化（embedding）
3) 在向量空间聚类，得到二维列表 `List[List[Entity]]`
4) 对每个簇调用大模型进行融合（输出 canonical_name、aliases、description）
5) 在代码侧做关系重定向：把关系两端的别名统一映射到 canonical_name
6) 得到“文档级”的去重实体与标准化关系

实现重点：
- **可运行性**：对 sentence-transformers / hdbscan / sklearn 做可选依赖处理。
  - 优先使用 sentence-transformers 做语义向量
  - 否则降级到 sklearn TF-IDF
  - 聚类优先用 hdbscan，否则用 sklearn DBSCAN；再不行则退化为“按名称精确分组”
- **可测试性**：支持注入 `llm_chat_fn`，单测时可用 fake LLM。
- **工程可控性**：融合阶段支持并发（semaphore 控制），避免实体多时过慢。
"""


from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from grag.monitoring.monitoring_manager import get_current_monitor

from ..config import get_config_manager

from ..model.embedding_client import EmbeddingClient
from ..model.llm_client import LLMClient
from .entity_relation_parser import ParsedEntity, ParsedRelation


KNOWLEDGE_FUSION_PROMPT = """
**Role (角色):**
你是一位资深的知识图谱编纂专家和数据融合工程师。你的任务是审查一组从不同来源抽取的、描述相似或相同实体的碎片化信息，并将它们整合成一个单一、权威、全面的知识实体。

**Goal (目标):**
对输入的 JSON 实体列表进行实体对齐（Entity Resolution）和知识融合（Knowledge Fusion）。
1.  **对齐 (Align)**: 识别出列表中哪些条目实际上是指向同一个现实世界对象的（例如，同义词、别名、全称与简称、不同语言的称呼等）。
2.  **融合 (Fuse)**: 将被对齐的所有实体的信息（类型、描述、属性）合并，生成一段全新的、信息密度更高、逻辑更连贯的综合描述。
3.  **标准化 (Standardize)**: 为合并后的实体确定一个最常用或最官方的“标准名称”（Canonical Name）。

**Input Format (输入格式):**
一个 JSON 列表，其中每个对象包含：`name` (名称), `type` (类型), `description` (来自不同文档的碎片化描述)。

**Output Format (输出格式):**
请仅输出一个合法的 JSON 列表，不要包含任何 Markdown 标记或解释性文字。
*   如果所有输入实体都被合并为一个，则列表只包含一个对象。
*   如果输入实体中有多个独立对象，则列表包含多个对象。

**输出 JSON 对象的结构:**
[
  {{
    "canonical_name": "标准名称 (最常用或最官方的名称)",
    "type": "统一后的最准确类型",
    "aliases": ["别名1", "别名2", "输入中的其他名称"],
    "description": "融合后的综合描述 (必须整合所有来源的核心事实，如时间、地点、关键属性、因果关系，50字以内)"
  }},
  ...
]

**Critical Rules (关键原则):**
1.  **保守合并原则**: 只有当你**高度确定**两个实体是同一个时才进行合并。如果存在歧义（例如，同名但描述明显不同），请将它们保留为独立的实体，并通过修改 `canonical_name` 来区分，例如 `李明 (歌手)` 和 `李明 (教授)`。
2.  **信息无损原则**: 融合后的 `description` 必须包含所有被合并实体描述中的**核心事实**，不能丢失重要信息。如果信息有时间先后，请按时间顺序组织。
3.  **类型选择**: `type` 应选择最具体、最准确的那个。例如，在 `Organization` 和 `Company` 中选择 `Company`。

***

**Example (示例):**

**Input:**
[
  {{"name": "国际商业机器公司", "type": "Organization", "description": "一家美国的跨国科技公司，总部位于纽约州阿蒙克。"}},
  {{"name": "IBM", "type": "Company", "description": "在2011年开发了问答电脑系统“沃森”。"}},
  {{"name": "深蓝", "type": "Product", "description": "IBM公司研发的，在1997年击败国际象棋世界冠军卡斯帕罗夫的超级计算机。"}},
  {{"name": "沃森", "type": "AI System", "description": "一种能够回答自然语言问题的人工智能程序。"}}
]

**Output:**
[
  {{
    "canonical_name": "IBM",
    "type": "Company",
    "aliases": ["国际商业机器公司"],
    "description": "一家总部位于纽约州阿蒙克的美国跨国科技公司，开发了著名的人工智能系统“沃森”(2011年)和超级计算机“深蓝”(1997年)。"
  }},
  {{
    "canonical_name": "深蓝",
    "type": "Product",
    "aliases": [],
    "description": "由IBM公司研发的超级计算机，在1997年击败了国际象棋世界冠军加里·卡斯帕罗夫。"
  }},
  {{
    "canonical_name": "沃森",
    "type": "AI System",
    "aliases": [],
    "description": "由IBM公司于2011年开发的一种能够回答自然语言问题的人工智能计算机系统。"
  }}
]

***

**待处理实体列表 (JSON):**
{entities_json}
"""


@dataclass(frozen=True)
class EntityForFusion:
    """用于“文档内部融合”的最小实体表示。"""

    entity_id: str
    name: str
    type: str
    description: str
    chunk_id: Optional[str] = None


@dataclass(frozen=True)
class FusedEntity:
    """LLM 融合后的标准实体。"""

    canonical_name: str
    type: str
    aliases: List[str]
    description: str


@dataclass(frozen=True)
class EntityCluster:
    """聚类产物：一簇相似实体。"""

    cluster_id: int
    members: List[EntityForFusion]


@dataclass(frozen=True)
class IntraDocumentFusionResult:
    """文档内部实体统一与关系重写的结果。"""

    fused_entities: List[FusedEntity]
    rewritten_relations: List[ParsedRelation]
    alias_to_canonical: Dict[str, str]
    clusters: List[EntityCluster]
    errors: List[str]


def _normalize_name(name: str) -> str:
    """对实体名称做轻量归一化（仅 trim）。"""

    return (name or "").strip()


def _entity_text_for_vectorization(e: EntityForFusion) -> str:
    """将实体拼成用于向量化的文本（name + type + description）。"""

    name = _normalize_name(e.name)
    etype = (e.type or "").strip()
    desc = (e.description or "").strip()
    return f"{name}｜{etype}｜{desc}".strip("｜")


def _get_embedding_provider_from_config() -> str:
    """从配置里决定本次向量化所用的 embedding provider。

    规则：
    - 优先读取 graph_construction.entity_resolution_knowledge_fusion.embedding_provider
    - 如果为 None/null，则取 embedding_providers 的第一个 key（按 yaml 顺序）
    """

    settings = get_config_manager().get_settings()
    cfg = settings.graph_construction.entity_resolution_knowledge_fusion

    provider = None
    if isinstance(cfg, dict):
        provider = cfg.get("embedding_provider")
    else:
        provider = getattr(cfg, "embedding_provider", None)

    if provider:
        return str(provider)

    # 取 embedding_providers 的第一个 key
    providers = getattr(settings, "embedding_providers", {})
    if isinstance(providers, dict) and providers:
        return str(next(iter(providers.keys())))

    # 理论上不应发生：settings 校验会要求 embedding_providers 非空
    raise RuntimeError("embedding_providers is empty; cannot select embedding provider")


def embed_entities(
    entities: List[EntityForFusion],
    *,
    embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
) -> Tuple[List[List[float]], List[str]]:
    """对实体列表做向量化。

    Returns:
        embeddings: 与 entities 同长度的向量列表
        errors: 向量化过程中产生的错误信息
    """

    errors: List[str] = []
    texts = [_entity_text_for_vectorization(e) for e in entities]

    monitor = get_current_monitor()
    if monitor is not None:
        monitor.observe("fusion.embedding.input_entities", float(len(entities)))

    # 注意：本项目要求“只读取配置中的模型”，因此这里不做 sentence-transformers / tfidf 等无关模型的自动 fallback。
    provider = _get_embedding_provider_from_config()
    try:
        if monitor is not None:
            with monitor.span("fusion.embedding", provider=provider, n=len(texts)):
                if embedding_fn is not None:
                    return embedding_fn(texts, provider), errors
                client = EmbeddingClient(provider_name=provider)
                return client.embed_texts(texts), errors

        if embedding_fn is not None:
            return embedding_fn(texts, provider), errors
        client = EmbeddingClient(provider_name=provider)
        return client.embed_texts(texts), errors
    except Exception as e:
        if monitor is not None:
            monitor.inc("fusion.embedding.errors", 1)
        raise RuntimeError(f"entity embedding failed (provider={provider}): {type(e).__name__}: {e}") from e


def cluster_entities(
    entities: List[EntityForFusion],
    embeddings: List[List[float]],
    *,
    method: str = "hdbscan",
    min_cluster_size: int = 2,
) -> Tuple[List[EntityCluster], List[str]]:
    """将实体按向量相似度聚类，得到二维列表。

    聚类策略：
    - 默认 hdbscan
    - 可配置为 exact_name：按实体名称精确分组（用于无 hdbscan 环境或测试）
    """

    errors: List[str] = []
    if not entities:
        return [], errors

    monitor = get_current_monitor()
    if monitor is not None:
        monitor.observe("fusion.clustering.input_entities", float(len(entities)))

    method = (method or "").strip().lower()
    if method == "exact_name":
        if monitor is not None:
            with monitor.span("fusion.clustering", method=method, min_cluster_size=int(min_cluster_size)):
                by_name: Dict[str, List[EntityForFusion]] = {}
                for e in entities:
                    by_name.setdefault(_normalize_name(e.name), []).append(e)
                clusters = [EntityCluster(cluster_id=i, members=m) for i, m in enumerate(by_name.values())]
                monitor.observe("fusion.clustering.output_clusters", float(len(clusters)))
                return clusters, errors

        by_name: Dict[str, List[EntityForFusion]] = {}
        for e in entities:
            by_name.setdefault(_normalize_name(e.name), []).append(e)
        clusters = [EntityCluster(cluster_id=i, members=m) for i, m in enumerate(by_name.values())]
        return clusters, errors

    if method != "hdbscan":
        raise ValueError(f"unsupported clustering method: {method}")

    if monitor is not None:
        with monitor.span("fusion.clustering", method=method, min_cluster_size=int(min_cluster_size)):
            # hdbscan 是默认且推荐方式：如果缺依赖，给出明确错误，不做悄悄降级。
            try:
                import hdbscan  # type: ignore
            except Exception as e:
                monitor.inc("fusion.clustering.errors", 1)
                raise RuntimeError(
                    "hdbscan is required for clustering method 'hdbscan'. "
                    "Please install hdbscan or set clustering.method=exact_name for testing. "
                    f"ImportError: {e}"
                ) from e

            clusterer = hdbscan.HDBSCAN(min_cluster_size=max(2, int(min_cluster_size)))
            labels = clusterer.fit_predict(embeddings)

            # labels == -1 表示噪声点；保留为单独 cluster，避免丢信息
            groups: Dict[int, List[EntityForFusion]] = {}
            next_noise_id = 10_000_000
            noise_points = 0
            for e, lb in zip(entities, labels):
                lb = int(lb)
                if lb == -1:
                    noise_points += 1
                    groups[next_noise_id] = [e]
                    next_noise_id += 1
                else:
                    groups.setdefault(lb, []).append(e)

            clusters = [
                EntityCluster(cluster_id=k, members=v) for k, v in sorted(groups.items(), key=lambda x: x[0])
            ]
            monitor.observe("fusion.clustering.output_clusters", float(len(clusters)))
            monitor.observe("fusion.clustering.noise_points", float(noise_points))
            return clusters, errors

    # no monitor
    try:
        import hdbscan  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "hdbscan is required for clustering method 'hdbscan'. "
            "Please install hdbscan or set clustering.method=exact_name for testing. "
            f"ImportError: {e}"
        ) from e

    clusterer = hdbscan.HDBSCAN(min_cluster_size=max(2, int(min_cluster_size)))
    labels = clusterer.fit_predict(embeddings)

    groups: Dict[int, List[EntityForFusion]] = {}
    next_noise_id = 10_000_000
    for e, lb in zip(entities, labels):
        lb = int(lb)
        if lb == -1:
            groups[next_noise_id] = [e]
            next_noise_id += 1
        else:
            groups.setdefault(lb, []).append(e)

    clusters = [EntityCluster(cluster_id=k, members=v) for k, v in sorted(groups.items(), key=lambda x: x[0])]
    return clusters, errors


def _build_entities_json_for_prompt(cluster: EntityCluster) -> str:
    """把一个簇的实体序列化为 prompt 输入 JSON。"""

    payload = [{"name": m.name, "type": m.type, "description": m.description} for m in cluster.members]
    return json.dumps(payload, ensure_ascii=False)


def _sanitize_json_output(raw: str) -> str:
    """清洗模型输出，移除思考内容、代码块和首尾解释文本。"""
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "").strip()
    return text


def _extract_first_json_value(raw: str) -> str:
    """从混杂文本中抽取第一个完整 JSON 值。"""
    text = _sanitize_json_output(raw)
    if not text:
        return ""

    start = -1
    open_char = ""
    close_char = ""
    for idx, ch in enumerate(text):
        if ch in "[{":
            start = idx
            open_char = ch
            close_char = "]" if ch == "[" else "}"
            break
    if start < 0:
        return text

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:]


def _fallback_fused_entities_from_cluster(cluster: EntityCluster) -> List[FusedEntity]:
    """当 LLM 融合失败时，按名称做保守兜底，避免整篇文档没有实体。"""
    by_name: Dict[str, List[EntityForFusion]] = {}
    for member in cluster.members:
        name = _normalize_name(member.name)
        if not name:
            continue
        by_name.setdefault(name, []).append(member)

    out: List[FusedEntity] = []
    for canonical_name, members in by_name.items():
        descriptions = [m.description.strip() for m in members if (m.description or "").strip()]
        aliases = sorted(
            {
                _normalize_name(m.name)
                for m in members
                if _normalize_name(m.name) and _normalize_name(m.name) != canonical_name
            }
        )
        entity_type = next((m.type.strip() for m in members if (m.type or "").strip()), "")
        description = max(descriptions, key=len) if descriptions else ""
        out.append(
            FusedEntity(
                canonical_name=canonical_name,
                type=entity_type or "Unknown",
                aliases=aliases,
                description=description,
            )
        )
    return out


def _parse_fused_entities_json(raw: str) -> Tuple[List[FusedEntity], List[str]]:
    """解析 LLM 融合输出 JSON。"""

    errors: List[str] = []
    txt = _extract_first_json_value(raw)
    if not txt:
        return [], ["empty LLM fusion output"]

    try:
        data = json.loads(txt)
    except Exception as e:
        return [], [f"invalid fusion JSON: {type(e).__name__}: {e}"]

    if not isinstance(data, list):
        return [], ["fusion JSON must be a list"]

    out: List[FusedEntity] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"fusion item {i}: not an object")
            continue

        canonical_name = str(item.get("canonical_name") or "").strip()
        etype = str(item.get("type") or "").strip()
        aliases_raw = item.get("aliases")
        desc = str(item.get("description") or "").strip()

        if not canonical_name:
            errors.append(f"fusion item {i}: missing canonical_name")
            continue
        if not etype:
            errors.append(f"fusion item {i}: missing type")
            continue

        aliases: List[str] = []
        if isinstance(aliases_raw, list):
            aliases = [str(x).strip() for x in aliases_raw if str(x).strip()]
        elif aliases_raw is None:
            aliases = []
        else:
            errors.append(f"fusion item {i}: aliases must be a list")

        out.append(
            FusedEntity(
                canonical_name=canonical_name,
                type=etype,
                aliases=aliases,
                description=desc,
            )
        )
    return out, errors


async def fuse_one_cluster(
    cluster: EntityCluster,
    *,
    llm_chat_fn: Optional[Callable[[str], str]] = None,
    llm_provider: Optional[str] = None,
) -> Tuple[EntityCluster, List[FusedEntity], List[str]]:
    """对一个簇调用 LLM 做融合。"""

    entities_json = _build_entities_json_for_prompt(cluster)
    prompt = KNOWLEDGE_FUSION_PROMPT.format(entities_json=entities_json)

    if llm_chat_fn is None:
        llm_chat_fn = LLMClient(llm_provider).chat

    try:
        monitor = get_current_monitor()
        if monitor is not None:
            monitor.inc("fusion.llm_calls", 1)
            with monitor.span("fusion.llm_fuse_one_cluster", cluster_id=cluster.cluster_id, size=len(cluster.members)):
                llm_raw = await asyncio.to_thread(llm_chat_fn, prompt)
        else:
            llm_raw = await asyncio.to_thread(llm_chat_fn, prompt)
        fused, parse_errors = _parse_fused_entities_json(llm_raw)
        if not fused:
            fused = _fallback_fused_entities_from_cluster(cluster)
            parse_errors.append("fusion fallback: use cluster members as fused entities")
        if monitor is not None:
            monitor.observe("fusion.llm_fused_entities", float(len(fused)))
            if parse_errors:
                monitor.observe("fusion.llm_parse_errors", float(len(parse_errors)))
        return cluster, fused, parse_errors
    except Exception as e:
        monitor = get_current_monitor()
        if monitor is not None:
            monitor.inc("fusion.llm_errors", 1)
        return (
            cluster,
            _fallback_fused_entities_from_cluster(cluster),
            [f"LLM fusion failed: {type(e).__name__}: {e}", "fusion fallback: use cluster members as fused entities"],
        )


async def fuse_clusters(
    clusters: List[EntityCluster],
    *,
    llm_chat_fn: Optional[Callable[[str], str]] = None,
    llm_provider: Optional[str] = None,
    bench_num: int = 4,
) -> Tuple[List[FusedEntity], List[str]]:
    """并发融合多个簇。"""

    errors: List[str] = []
    if not clusters:
        return [], errors

    if bench_num <= 0:
        bench_num = 1

    sem = asyncio.Semaphore(int(bench_num))

    async def _run(c: EntityCluster):
        async with sem:
            return await fuse_one_cluster(c, llm_chat_fn=llm_chat_fn, llm_provider=llm_provider)

    tasks = [asyncio.create_task(_run(c)) for c in clusters]
    results = await asyncio.gather(*tasks)

    fused_all: List[FusedEntity] = []
    for cluster, fused, errs in results:
        fused_all.extend(fused)
        for er in errs:
            errors.append(f"cluster {cluster.cluster_id}: {er}")

    monitor = get_current_monitor()
    if monitor is not None:
        monitor.observe("fusion.llm_clusters", float(len(clusters)))
        monitor.observe("fusion.llm_total_fused_entities", float(len(fused_all)))
        monitor.observe("fusion.llm_total_errors", float(len(errors)))
    return fused_all, errors


def build_alias_to_canonical_map(
    fused_entities: Sequence[FusedEntity],
    *,
    include_canonical_self: bool = True,
) -> Dict[str, str]:
    """构建 alias -> canonical 的映射表，用于关系重定向。"""

    m: Dict[str, str] = {}
    for fe in fused_entities:
        canonical = _normalize_name(fe.canonical_name)
        if include_canonical_self and canonical:
            m.setdefault(canonical, canonical)
        for a in fe.aliases:
            alias = _normalize_name(a)
            if not alias:
                continue
            m.setdefault(alias, canonical)
    return m


def rewrite_relations_with_alias_map(
    relations: Sequence[ParsedRelation],
    alias_to_canonical: Dict[str, str],
) -> List[ParsedRelation]:
    """将关系中的 subject/object 用 canonical_name 重写。"""

    out: List[ParsedRelation] = []
    for r in relations:
        subj = _normalize_name(r.subject)
        obj = _normalize_name(r.object)
        new_subj = alias_to_canonical.get(subj, subj)
        new_obj = alias_to_canonical.get(obj, obj)
        out.append(
            ParsedRelation(
                subject=new_subj,
                object=new_obj,
                description=r.description,
                relation_type=r.relation_type,
                confidence=r.confidence,
            )
        )
    return out


def collect_entities_from_chunks(
    chunks: Iterable[Tuple[str, Sequence[ParsedEntity]]],
) -> List[EntityForFusion]:
    """把 chunk 里的实体展平成实体列表，并补充 chunk_id 便于调试。"""

    out: List[EntityForFusion] = []
    idx = 0
    for chunk_id, ents in chunks:
        for e in ents:
            idx += 1
            out.append(
                EntityForFusion(
                    entity_id=f"e{idx}",
                    name=e.name,
                    type=e.type,
                    description=e.description,
                    chunk_id=chunk_id,
                )
            )
    return out


async def resolve_and_fuse_intra_document(
    *,
    entities: List[EntityForFusion],
    relations: List[ParsedRelation],
    llm_chat_fn: Optional[Callable[[str], str]] = None,
    embedding_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None,
    cluster_min_size: int = 2,
) -> IntraDocumentFusionResult:
    """对单篇文档执行：实体聚类 + LLM 融合 + 关系重定向。"""

    errors: List[str] = []
    if not entities:

        return IntraDocumentFusionResult(
            fused_entities=[],
            rewritten_relations=list(relations),
            alias_to_canonical={},
            clusters=[],
            errors=["no entities provided"],
        )

    monitor = get_current_monitor()
    if monitor is not None:
        monitor.observe("fusion.input_entities", float(len(entities)))
        monitor.observe("fusion.input_relations", float(len(relations)))

    # Step 2) 向量化
    embeddings, emb_errors = embed_entities(entities, embedding_fn=embedding_fn)
    errors.extend(emb_errors)

    # Step 3) 聚类
    settings = get_config_manager().get_settings()
    cfg = settings.graph_construction.entity_resolution_knowledge_fusion
    clustering_cfg = cfg.get("clustering", {}) if isinstance(cfg, dict) else getattr(cfg, "clustering", {})
    method = clustering_cfg.get("method", "hdbscan") if isinstance(clustering_cfg, dict) else "hdbscan"
    min_cluster_size = clustering_cfg.get("min_cluster_size", cluster_min_size) if isinstance(clustering_cfg, dict) else cluster_min_size

    fusion_bench_num = cfg.get("fusion_bench_num", 4) if isinstance(cfg, dict) else getattr(cfg, "fusion_bench_num", 4)
    fusion_llm_provider = cfg.get("fusion_llm_provider") if isinstance(cfg, dict) else getattr(cfg, "fusion_llm_provider", None)

    clusters, cluster_errors = cluster_entities(
        entities,
        embeddings,
        method=str(method),
        min_cluster_size=int(min_cluster_size),
    )
    errors.extend(cluster_errors)

    if monitor is not None:
        monitor.observe("fusion.clusters", float(len(clusters)))

    # Step 4) LLM 知识融合
    if monitor is not None:
        with monitor.span("fusion.llm_fusion", clusters=len(clusters), bench_num=int(fusion_bench_num)):
            fused_entities, fuse_errors = await fuse_clusters(
                clusters,
                llm_chat_fn=llm_chat_fn,
                llm_provider=str(fusion_llm_provider) if fusion_llm_provider else None,
                bench_num=int(fusion_bench_num) if fusion_bench_num else 4,
            )
    else:
        fused_entities, fuse_errors = await fuse_clusters(
            clusters,
            llm_chat_fn=llm_chat_fn,
            llm_provider=str(fusion_llm_provider) if fusion_llm_provider else None,
            bench_num=int(fusion_bench_num) if fusion_bench_num else 4,
        )
    errors.extend(fuse_errors)

    # Step 5) 关系重定向
    if monitor is not None:
        with monitor.span("fusion.rewrite_relations"):
            alias_map = build_alias_to_canonical_map(fused_entities)
            rewritten_relations = rewrite_relations_with_alias_map(relations, alias_map)
    else:
        alias_map = build_alias_to_canonical_map(fused_entities)
        rewritten_relations = rewrite_relations_with_alias_map(relations, alias_map)

    if monitor is not None:
        monitor.observe("fusion.alias_map", float(len(alias_map)))
        monitor.observe("fusion.output_fused_entities", float(len(fused_entities)))
        monitor.observe("fusion.output_rewritten_relations", float(len(rewritten_relations)))
        monitor.observe("fusion.output_errors", float(len(errors)))

    return IntraDocumentFusionResult(
        fused_entities=fused_entities,
        rewritten_relations=rewritten_relations,
        alias_to_canonical=alias_map,
        clusters=clusters,
        errors=errors,
    )
