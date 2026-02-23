# Results Reranking Module

"""grag.retrieval.utils.reranker

检索结果重排序（Rerank）模块。

说明：
- 该文件从原 `grag.retrieval.reranker` 迁移到 `grag.retrieval.utils`，便于检索层复用。
- 老路径会保留 shim（re-export），以保证向后兼容。

设计原则（很重要）：
- rerank 属于“精排”，是可选能力：
  - 未配置 provider 或 provider 不可用时，必须返回原始顺序（稳定降级）。
  - provider 调用异常时，也必须返回原始顺序（避免影响主检索链路）。
- 本实现不会修改 hit/node 的结构，只会调整返回列表顺序。

为什么需要“按文本映射回原对象”：
- 当前 `RerankerClient.rerank()` 返回的是 `(document_text, score)`，而不是返回索引。
- 因此我们通过 `text -> [index...]` 的队列映射，把 rerank 结果稳定映射回原始对象。
- 如果存在重复 text（很常见），队列策略能保证每个重复项都能被依次消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple, TypeVar

from grag.model.reranker_client import RerankerClient


class _HasText(Protocol):
    """用于约束 chunk hit：只要具备 `text: str` 就可参与 rerank。"""
    text: str


T = TypeVar("T", bound=_HasText)


@dataclass(frozen=True)
class RerankDebugInfo:
    """rerank 调试信息。

    说明：
    - 该结构主要用于上层做观测/日志（例如统计是否启用 rerank、输入输出数量）。
    - 不参与检索逻辑。
    """
    enabled: bool
    provider_name: Optional[str]
    input_size: int
    output_size: int


def _build_graph_node_text(node: dict) -> str:
    """把图节点 dict 转成可用于 rerank 的“文本”。

    图检索返回的 node 是结构化字段（name/type/description/aliases/doc_name...）。
    rerank 模型通常更擅长处理自然语言，因此这里做一次“字段拼接”。
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
    - 只重排 nodes，不改变 edges。
    - 未配置/不可用/失败必须稳定降级为原顺序。
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

    返回：
    - reranked hits
    - debug info

    降级策略：
    - query 为空 / hits 为空：不做处理
    - reranker provider 不可用：返回原始 hits
    """
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

    index_queue_by_text: dict[str, List[int]] = {}
    for i, t in enumerate(docs):
        index_queue_by_text.setdefault(t, []).append(i)

    reranked_docs_with_score: List[Tuple[str, float]] = client.rerank(
        query,
        docs,
        top_k=top_k,
    )

    ordered: List[T] = []
    used: set[int] = set()

    for doc_text, _score in reranked_docs_with_score:
        q = index_queue_by_text.get(doc_text)
        if not q:
            continue
        idx = q.pop(0)
        if idx in used:
            continue
        used.add(idx)
        ordered.append(hits[idx])

    if len(ordered) < len(hits):
        for i, h in enumerate(hits):
            if i in used:
                continue
            ordered.append(h)

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
