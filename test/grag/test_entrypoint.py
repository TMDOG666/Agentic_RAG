from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest


@dataclass(frozen=True)
class _Sentinel:
    name: str


def test_grag_build_kg_wires_storage_and_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    import grag.entrypoint as ep

    called = {
        "init": 0,
        "storage": None,
        "build_kwargs": None,
    }

    class _FakeCM:
        def initialize(self):
            called["init"] += 1
            return True

    class FakeStorage:
        def __init__(
            self,
            *,
            milvus_collection_name=None,
            milvus_graph_index_collection_name=None,
            milvus_upsert_strategy=None,
        ):
            called["storage"] = {
                "milvus_collection_name": milvus_collection_name,
                "milvus_graph_index_collection_name": milvus_graph_index_collection_name,
                "milvus_upsert_strategy": milvus_upsert_strategy,
            }

    class FakeBuilder:
        def __init__(self, *, storage):
            self._storage = storage

        def build_and_save(self, **kwargs):
            called["build_kwargs"] = dict(kwargs)
            return _Sentinel("build_result")

    monkeypatch.setattr(ep, "get_config_manager", lambda: _FakeCM())
    monkeypatch.setattr(ep, "DataClientGraphStorage", FakeStorage)
    monkeypatch.setattr(ep, "GraphBuilder", FakeBuilder)

    api = ep.GRAG(build_options=ep.BuildOptions(milvus_collection_name="c0", milvus_upsert_strategy="s0"))
    out = api.build_kg(
        text="t",
        doc_time="2026-01-01T00:00:00+00:00",
        doc_name="n",
        group_id="g",
        doc_id="d",
    )

    assert out == _Sentinel("build_result")
    assert called["init"] == 1
    assert called["storage"] == {
        "milvus_collection_name": "c0",
        "milvus_graph_index_collection_name": None,
        "milvus_upsert_strategy": "s0",
    }
    assert called["build_kwargs"] == {
        "text": "t",
        "doc_time": "2026-01-01T00:00:00+00:00",
        "doc_name": "n",
        "group_id": "g",
        "doc_id": "d",
    }


def test_grag_build_kg_allows_overriding_collection_and_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    import grag.entrypoint as ep

    called = {"storage": None}

    class _FakeCM:
        def initialize(self):
            return True

    monkeypatch.setattr(ep, "get_config_manager", lambda: _FakeCM())

    class FakeStorage:
        def __init__(
            self,
            *,
            milvus_collection_name=None,
            milvus_graph_index_collection_name=None,
            milvus_upsert_strategy=None,
        ):
            called["storage"] = {
                "milvus_collection_name": milvus_collection_name,
                "milvus_graph_index_collection_name": milvus_graph_index_collection_name,
                "milvus_upsert_strategy": milvus_upsert_strategy,
            }

    class FakeBuilder:
        def __init__(self, *, storage):
            self._storage = storage

        def build_and_save(self, **kwargs):
            return _Sentinel("build_result")

    monkeypatch.setattr(ep, "DataClientGraphStorage", FakeStorage)
    monkeypatch.setattr(ep, "GraphBuilder", FakeBuilder)

    api = ep.GRAG(build_options=ep.BuildOptions(milvus_collection_name="c0", milvus_upsert_strategy="s0"))
    api.build_kg(
        text="t",
        doc_time="2026-01-01T00:00:00+00:00",
        doc_name="n",
        group_id="g",
        milvus_collection_name="c1",
        milvus_upsert_strategy="s1",
    )

    assert called["storage"] == {
        "milvus_collection_name": "c1",
        "milvus_graph_index_collection_name": None,
        "milvus_upsert_strategy": "s1",
    }


def test_grag_query_wires_retrieval_manager_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    import grag.entrypoint as ep

    called = {
        "init": 0,
        "rm_collection": None,
        "rm_graph_index_collection": None,
        "search_kwargs": None,
    }

    def fake_init():
        called["init"] += 1

    class _FakeCM:
        def initialize(self):
            fake_init()
            return True

    class FakeRM:
        def __init__(self, *, milvus_collection_name=None, milvus_graph_index_collection_name=None):
            called["rm_collection"] = milvus_collection_name
            called["rm_graph_index_collection"] = milvus_graph_index_collection_name

        def keyword(self, **kwargs):
            called["search_kwargs"] = dict(kwargs)
            return _Sentinel("retrieval_result")

    monkeypatch.setattr(ep, "get_config_manager", lambda: _FakeCM())
    monkeypatch.setattr(ep, "RetrievalManager", FakeRM)

    api = ep.GRAG(query_options=ep.QueryOptions(milvus_collection_name="cQ"))
    out = api.keyword(
        group_id="g",
        query="q",
        top_k=7,
        doc_id="d",
        doc_time_start="2026-01-01T00:00:00+00:00",
        doc_time_end="2026-02-01T00:00:00+00:00",
        rerank_enabled=False,
        rerank_provider="p",
        milvus_collection_name=None,
        milvus_graph_index_collection_name=None,
    )

    assert out == _Sentinel("retrieval_result")
    assert called["init"] == 1
    assert called["rm_collection"] == "cQ"
    assert called["rm_graph_index_collection"] is None
    assert called["search_kwargs"] == {
        "group_id": "g",
        "query": "q",
        "top_k": 7,
        "doc_id": "d",
        "doc_time_start": "2026-01-01T00:00:00+00:00",
        "doc_time_end": "2026-02-01T00:00:00+00:00",
        "rerank_enabled": False,
        "rerank_provider": "p",
    }


def test_grag_default_query_collection_follows_build_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import grag.entrypoint as ep

    called = {"rm_collection": None}

    class _FakeCM:
        def initialize(self):
            return True

    monkeypatch.setattr(ep, "get_config_manager", lambda: _FakeCM())

    class FakeRM:
        def __init__(self, *, milvus_collection_name=None, milvus_graph_index_collection_name=None):
            called["rm_collection"] = milvus_collection_name

        def native(self, **kwargs):
            return _Sentinel("retrieval_result")

    monkeypatch.setattr(ep, "RetrievalManager", FakeRM)

    api = ep.GRAG(build_options=ep.BuildOptions(milvus_collection_name="c0"))
    api.native(group_id="g", query="q")

    assert called["rm_collection"] == "c0"


@pytest.mark.integration
def test_grag_entrypoint_real_build_and_query(real_doc_texts, pytestconfig) -> None:
    """使用 GRAG 总入口跑真实流程：入库（Postgres/Milvus/Neo4j）+ 查询（keyword/semantic/graph）。

    说明：
    - 该用例会调用真实外部服务与模型（embedding/LLM），耗时较长。
    - 默认会清理本次创建的数据；可用 --no-cleanup 保留数据，便于通过 Attu/Neo4j Browser 手工检查。
    """

    from grag import BuildOptions, GRAG

    from test.grag.retrieval.test_full_retrieval_integration import (
        _cleanup_milvus,
        _cleanup_neo4j,
        _cleanup_postgres,
        _drop_milvus_collection,
        _pick_graph_entity_name,
        _pick_keyword_query,
        _pick_semantic_query,
    )

    assert len(real_doc_texts) >= 2

    group_id = f"pytest_ep_{uuid4().hex[:8]}"
    collection_name = f"pytest_ep_{uuid4().hex[:10]}"

    pause_s = float(pytestconfig.getoption("pause") or 0)
    no_cleanup = bool(pytestconfig.getoption("no_cleanup"))

    api = GRAG(build_options=BuildOptions(milvus_collection_name=collection_name))

    created_doc_ids: list[str] = []
    created_chunk_ids: list[str] = []

    first_doc_id: str | None = None
    example_chunk_text: str = ""

    try:
        # 1) 入库两篇文档
        for i, (p, text) in enumerate(real_doc_texts[:2]):
            doc_id = f"doc_{i}_{uuid4().hex[:8]}"
            doc_name = p.stem
            doc_time = datetime.now(timezone.utc).isoformat()
            snippet = (text or "")[:6000]

            build_res = api.build_kg(
                text=snippet,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
            )

            created_doc_ids.append(doc_id)
            created_chunk_ids.extend([c.chunk_id for c in build_res.chunks])

            assert build_res.document.group_id == group_id
            assert build_res.document.doc_id == doc_id
            assert len(build_res.chunks) > 0

            if first_doc_id is None:
                first_doc_id = doc_id
                example_chunk_text = build_res.chunks[0].text or ""

        assert first_doc_id is not None

        # 2) keyword
        keyword_q = _pick_keyword_query(example_chunk_text)
        print("\n[Keyword] query=", repr(keyword_q))
        keyword_res = api.keyword(
            group_id=group_id,
            query=keyword_q,
            top_k=10,
            rerank_enabled=False,
            milvus_collection_name=collection_name,
        )
        print("[Keyword] hits=", len(keyword_res.keyword_hits))
        for i, h in enumerate(keyword_res.keyword_hits[:3]):
            print(
                f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} index={h.index} text={repr((h.text or '')[:120])}"
            )
        assert len(keyword_res.keyword_hits) > 0

        # 3) native
        semantic_q = _pick_semantic_query(example_chunk_text)
        print("\n[Native] query=", repr(semantic_q))
        native_res = api.native(
            group_id=group_id,
            query=semantic_q,
            top_k=10,
            rerank_enabled=False,
            milvus_collection_name=collection_name,
        )
        print("[Native] hits=", len(native_res.semantic_hits))
        assert len(native_res.semantic_hits) > 0

        # 4) local / global
        entity_name = _pick_graph_entity_name(group_id=group_id, doc_id=first_doc_id)
        if not entity_name:
            pytest.skip("No entity extracted for local/global retrieval in this run")
        highlow = f"{entity_name}>{entity_name}"

        print("\n[Local] highlow=", repr(highlow))
        local_res = api.local(
            group_id=group_id,
            query=semantic_q,
            graph_entity_name=highlow,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
            milvus_collection_name=collection_name,
        )
        assert local_res.local_graph is not None
        print("[Local] nodes=", len(local_res.local_graph.nodes), "edges=", len(local_res.local_graph.edges))

        print("\n[Global] highlow=", repr(highlow))
        global_res = api.global_(
            group_id=group_id,
            query=semantic_q,
            graph_entity_name=highlow,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
            milvus_collection_name=collection_name,
        )
        assert global_res.global_graph is not None
        print("[Global] nodes=", len(global_res.global_graph.nodes), "edges=", len(global_res.global_graph.edges))

    finally:
        if pause_s > 0:
            import time

            time.sleep(pause_s)

        if no_cleanup:
            return

        if created_chunk_ids:
            _cleanup_milvus(collection_name=collection_name, group_id=group_id, chunk_ids=created_chunk_ids)
        for doc_id in created_doc_ids:
            _cleanup_neo4j(group_id=group_id, doc_id=doc_id)
        if created_doc_ids:
            _cleanup_postgres(group_id=group_id, doc_ids=created_doc_ids)
        _drop_milvus_collection(collection_name=collection_name)
