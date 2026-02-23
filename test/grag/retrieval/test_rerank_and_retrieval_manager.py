"""检索与重排序（rerank）相关的单元测试。

设计目标：
- 不依赖真实外部服务（Postgres/Milvus/Neo4j/LLM/Embedding）。
- 覆盖 rerank 的关键行为：
  - reranker 不可用时稳定降级
  - rerank 后顺序发生变化（且能正确映射回原 hit）
- 覆盖 RetrievalManager 的 rerank_enabled 行为：
  - 开启后会对 keyword/semantic hits 调用 rerank

说明：
- 这里主要验证“管线行为与降级策略”，不验证外部服务的效果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pytest


@dataclass(frozen=True)
class _Hit:
    """最小可用的 chunk hit 结构，仅用于测试 rerank 映射逻辑。"""

    text: str
    id: str


class TestRerankChunkHits:
    def test_rerank_disabled_when_query_empty(self):
        from grag.retrieval.utils.reranker import rerank_chunk_hits

        hits = [_Hit(text="a", id="1"), _Hit(text="b", id="2")]
        ordered, info = rerank_chunk_hits(query="", hits=hits, top_k=10)

        assert ordered == hits
        assert info.enabled is False

    def test_rerank_fallback_when_reranker_not_available(self, monkeypatch: pytest.MonkeyPatch):
        import grag.retrieval.utils.reranker as reranker_mod

        class FakeClient:
            def __init__(self, provider_name: Optional[str] = None):
                self.provider_name = provider_name

            def is_available(self) -> bool:
                return False

        monkeypatch.setattr(reranker_mod, "RerankerClient", FakeClient)

        hits = [_Hit(text="doc1", id="1"), _Hit(text="doc2", id="2")]
        ordered, info = reranker_mod.rerank_chunk_hits(query="q", hits=hits, top_k=10)

        assert ordered == hits
        assert info.enabled is False

    def test_rerank_reorders_and_maps_back_to_hits(self, monkeypatch: pytest.MonkeyPatch):
        import grag.retrieval.utils.reranker as reranker_mod

        class FakeClient:
            def __init__(self, provider_name: Optional[str] = None):
                self.provider_name = provider_name

            def is_available(self) -> bool:
                return True

            def rerank(
                self, query: str, documents: List[str], top_k: Optional[int] = None
            ) -> List[Tuple[str, float]]:
                # 按文档文本倒序返回，模拟 reranker 改变顺序。
                out = [(d, float(i)) for i, d in enumerate(reversed(documents), start=1)]
                if top_k is not None:
                    out = out[: int(top_k)]
                return out

        monkeypatch.setattr(reranker_mod, "RerankerClient", FakeClient)

        hits = [_Hit(text="a", id="1"), _Hit(text="b", id="2"), _Hit(text="c", id="3")]
        ordered, info = reranker_mod.rerank_chunk_hits(query="q", hits=hits, top_k=2)

        assert [h.id for h in ordered] == ["3", "2"]
        assert info.enabled is True
        assert info.input_size == 3
        assert info.output_size == 2


class TestRetrievalManagerRerank:
    def test_retrieval_manager_reranks_keyword_hits(self, monkeypatch: pytest.MonkeyPatch):
        from grag.retrieval import RetrievalManager, RetrievalResult
        from grag.retrieval.keyword_retriever import KeywordChunkHit
        import grag.retrieval.base_retriever.base_retrieval_manager as rm_mod

        # 1) 构造一个不触发真实 DB 的 RetrievalManager 实例
        rm = RetrievalManager.__new__(RetrievalManager)

        class FakeKeyword:
            def search(self, **kwargs):
                return [
                    KeywordChunkHit(group_id="g", doc_id="d", chunk_id="1", index=0, text="A"),
                    KeywordChunkHit(group_id="g", doc_id="d", chunk_id="2", index=1, text="B"),
                ]

        class FakeSemantic:
            def search(self, **kwargs):
                return []

        class FakeGraph:
            def search(self, **kwargs):
                return None

        rm._keyword = FakeKeyword()
        rm._semantic = FakeSemantic()
        rm._graph = FakeGraph()

        # 2) monkeypatch rerank_chunk_hits：直接把 hits 反转
        def fake_rerank_chunk_hits(*, query, hits, top_k=None, provider_name=None):
            return (list(reversed(hits))[: int(top_k or len(hits))], None)

        monkeypatch.setattr(rm_mod, "rerank_chunk_hits", fake_rerank_chunk_hits)

        res = rm.search(
            group_id="g",
            query="q",
            modes=["keyword"],
            top_k=10,
            rerank_enabled=True,
            rerank_provider=None,
        )

        assert isinstance(res, RetrievalResult)
        assert [h.chunk_id for h in res.keyword_hits] == ["2", "1"]

    def test_group_id_required(self):
        from grag.retrieval import RetrievalManager

        rm = RetrievalManager.__new__(RetrievalManager)
        rm._keyword = object()
        rm._semantic = object()
        rm._graph = object()

        with pytest.raises(ValueError):
            rm.search(group_id="", query="q", modes=["keyword"])  # type: ignore[arg-type]

    def test_retrieval_manager_reranks_graph_nodes(self, monkeypatch: pytest.MonkeyPatch):
        from grag.retrieval import RetrievalManager, RetrievalResult
        from grag.retrieval.graph_retriever import GraphSubgraphResult
        import grag.retrieval.base_retriever.base_retrieval_manager as rm_mod

        rm = RetrievalManager.__new__(RetrievalManager)

        class FakeKeyword:
            def search(self, **kwargs):
                return []

        class FakeSemantic:
            def search(self, **kwargs):
                return []

        class FakeGraph:
            def search(self, **kwargs):
                return GraphSubgraphResult(
                    nodes=[
                        {"name": "A", "description": "aaa"},
                        {"name": "B", "description": "bbb"},
                    ],
                    edges=[{"type": "REL"}],
                )

        rm._keyword = FakeKeyword()
        rm._semantic = FakeSemantic()
        rm._graph = FakeGraph()

        def fake_rerank_graph_nodes(*, query, nodes, top_k=None, provider_name=None):
            return (list(reversed(nodes)), None)

        monkeypatch.setattr(rm_mod, "rerank_graph_nodes", fake_rerank_graph_nodes)

        res = rm.search(
            group_id="g",
            query="q",
            modes=["graph"],
            top_k=10,
            rerank_enabled=True,
        )

        assert isinstance(res, RetrievalResult)
        assert res.graph is not None
        assert [n.get("name") for n in res.graph.nodes] == ["B", "A"]
        # edges 不应被改变
        assert res.graph.edges == [{"type": "REL"}]
