# Results Reranking Module

"""grag.retrieval.reranker

检索结果重排序（Rerank）模块。

为什么需要重排序？
- 向量检索/关键词检索通常是“召回”阶段，目标是把可能相关的内容尽量找全。
- 重排序属于“精排”阶段，目标是把召回结果按与 query 的相关性重新排序。

本项目的实现原则：
- 重排序是可选能力：未配置重排序 provider 或调用失败时，必须安全降级为原顺序。
- 先支持对 chunk 类结果（keyword/semantic）做 rerank。
- 不改变原 hit 结构，只调整返回列表的顺序（避免对外 API 大改）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple, TypeVar

from grag.model.reranker_client import RerankerClient


class _HasText(Protocol):
    """用于约束 chunk hit 结构：只要有 text 字段就可以被重排序。"""

    text: str


T = TypeVar("T", bound=_HasText)


@dataclass(frozen=True)
class RerankDebugInfo:
    """调试信息（可选），用于在需要时追踪重排序过程。"""

    enabled: bool
    provider_name: Optional[str]
    input_size: int
    output_size: int


def _build_graph_node_text(node: dict) -> str:
    """把图节点转成可用于 rerank 的文本。

    约定：graph nodes 来自 Neo4jRepository.search_entity_subgraph()，字段通常包含：
    - name/type/description/aliases/doc_name/doc_time/labels

    这里使用“尽量多的信息拼接”策略：
    - rerank 模型更容易从自然语言字段判断相关性。
    - 即使部分字段缺失也不会报错。
    """

    name = str(node.get("name") or "").strip()
    typ = str(node.get("type") or "").strip()
    desc = str(node.get("description") or "").strip()
    doc_name = str(node.get("doc_name") or "").strip()

    aliases = node.get("aliases")
    if isinstance(aliases, (list, tuple)):
        alias_str = ", ".join([str(a).strip() for a in aliases if str(a).strip()])
    else:
        alias_str = str(aliases or "").strip()

    parts: list[str] = []
    if name:
        parts.append(f"name: {name}")
    if alias_str:
        parts.append(f"aliases: {alias_str}")
    if typ:
        parts.append(f"type: {typ}")
    if desc:
        parts.append(f"description: {desc}")
    if doc_name:
        parts.append(f"doc: {doc_name}")

    # 兜底：避免空字符串导致 reranker 不稳定。
    return "\n".join(parts).strip() or name or desc or "node"


def rerank_graph_nodes(
    *,
    query: str,
    nodes: Sequence[dict],
    top_k: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> Tuple[List[dict], RerankDebugInfo]:
    """对图检索返回的 nodes 做重排序。

    注意：
    - 这里只重排 nodes 顺序，不改 edges。
    - 与 chunk rerank 一样：未配置/失败时必须稳定降级。
    - node 可能存在文本重复（例如 name 相同），因此映射逻辑按“文本队列”处理。
    """

    if not str(query or "").strip() or not nodes:
        return (
            list(nodes),
            RerankDebugInfo(
                enabled=False,
                provider_name=provider_name,
                input_size=len(nodes),
                output_size=len(nodes),
            ),
        )

    client = RerankerClient(provider_name=provider_name)
    if not client.is_available():
        return (
            list(nodes),
            RerankDebugInfo(
                enabled=False,
                provider_name=provider_name,
                input_size=len(nodes),
                output_size=len(nodes),
            ),
        )

    texts: List[str] = [_build_graph_node_text(n) for n in nodes]

    index_queue_by_text: dict[str, List[int]] = {}
    for i, t in enumerate(texts):
        index_queue_by_text.setdefault(t, []).append(i)

    reranked_docs_with_score: List[Tuple[str, float]] = client.rerank(
        query,
        texts,
        top_k=top_k,
    )

    ordered: List[dict] = []
    used: set[int] = set()

    for doc_text, _score in reranked_docs_with_score:
        q = index_queue_by_text.get(doc_text)
        if not q:
            continue
        idx = q.pop(0)
        if idx in used:
            continue
        used.add(idx)
        ordered.append(nodes[idx])

    if len(ordered) < len(nodes):
        for i, n in enumerate(nodes):
            if i in used:
                continue
            ordered.append(n)

    if top_k is not None:
        ordered = ordered[: int(top_k)]

    return (
        ordered,
        RerankDebugInfo(
            enabled=True,
            provider_name=provider_name,
            input_size=len(nodes),
            output_size=len(ordered),
        ),
    )


def rerank_chunk_hits(
    *,
    query: str,
    hits: Sequence[T],
    top_k: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> Tuple[List[T], RerankDebugInfo]:
    """对 chunk hits 做重排序。

    Args:
        query: 用户查询。
        hits: 需要重排序的候选列表（元素必须有 text 字段）。
        top_k: 重排序后最多保留的数量；None 表示保留全部。
        provider_name: 可选，指定重排序 provider；None 表示使用 settings 默认 provider。

    Returns:
        (重排序后的 hits, debug_info)

    设计说明：
    - RerankerClient 当前接口返回 [(document_text, score)]，而不是返回索引。
      因此我们使用 "text -> index queue" 的方式把结果映射回原 hit。
    - 如果 text 有重复，队列能保证同一 text 的多个 hit 都能被稳定映射。
    - 若重排序不可用/失败，返回原 hits（稳定降级）。
    """

    # 基础入参检查：query 为空或 hits 为空时，不做任何处理。
    if not str(query or "").strip() or not hits:
        return (
            list(hits),
            RerankDebugInfo(
                enabled=False,
                provider_name=provider_name,
                input_size=len(hits),
                output_size=len(hits),
            ),
        )

    client = RerankerClient(provider_name=provider_name)

    # 未配置重排序服务：直接返回原顺序。
    if not client.is_available():
        return (
            list(hits),
            RerankDebugInfo(
                enabled=False,
                provider_name=provider_name,
                input_size=len(hits),
                output_size=len(hits),
            ),
        )

    docs: List[str] = [str(h.text or "") for h in hits]

    # text -> [index0, index1, ...]（用于处理重复文本）
    index_queue_by_text: dict[str, List[int]] = {}
    for i, t in enumerate(docs):
        index_queue_by_text.setdefault(t, []).append(i)

    # 执行重排序：RerankerClient 内部已做 try/except，会在失败时返回原始顺序。
    reranked_docs_with_score: List[Tuple[str, float]] = client.rerank(
        query,
        docs,
        top_k=top_k,
    )

    ordered: List[T] = []
    used: set[int] = set()

    # 1) 按 reranker 返回的顺序映射回 hit
    for doc_text, _score in reranked_docs_with_score:
        q = index_queue_by_text.get(doc_text)
        if not q:
            continue
        idx = q.pop(0)
        if idx in used:
            continue
        used.add(idx)
        ordered.append(hits[idx])

    # 2) 兜底：补齐未被映射到的候选（保持原始相对顺序）
    if len(ordered) < len(hits):
        for i, h in enumerate(hits):
            if i in used:
                continue
            ordered.append(h)

    # 3) 如果指定 top_k，则截断
    if top_k is not None:
        ordered = ordered[: int(top_k)]

    return (
        ordered,
        RerankDebugInfo(
            enabled=True,
            provider_name=provider_name,
            input_size=len(hits),
            output_size=len(ordered),
        ),
    )