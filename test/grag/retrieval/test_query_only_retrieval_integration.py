from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from typing import Any

import pytest

from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.retrieval import RetrievalManager


pytestmark = pytest.mark.filterwarnings(
    "ignore:Pydantic V1 style `@validator` validators are deprecated.*:DeprecationWarning"
)


def _jsonable(x: Any):
    if is_dataclass(x):
        return asdict(x)
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "__dict__"):
        return _jsonable(vars(x))
    return str(x)


def _maybe_print_result(*, title: str, res: Any, enabled: bool) -> None:
    if not enabled:
        return
    payload = _jsonable(res)
    print(f"\n[{title}] full_result(json)=")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


@pytest.mark.integration
def test_query_only_retrieval(pytestconfig) -> None:
    """只测试“查询/检索”模块：不做入库、不做抽取。

    使用方式：
    - 你需要提前准备好一份已经入库的数据（Postgres/Milvus/Neo4j）。
    - 运行本用例时通过 pytest options 传入 group_id、milvus collection 以及 query。
    """

    get_config_manager().initialize()
    dm = get_data_manager()

    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    group_id = str(pytestconfig.getoption("group_id") or "").strip()
    milvus_collection = str(pytestconfig.getoption("milvus_collection") or "").strip()

    milvus_collection_valid = True
    if milvus_collection:
        milvus_collection_valid = bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", milvus_collection))

    if not group_id:
        pytest.skip("Missing --group-id; this test only validates query path against existing data")

    keyword_q = str(pytestconfig.getoption("keyword_q") or "").strip()
    semantic_q = str(pytestconfig.getoption("semantic_q") or "").strip()
    native_q = str(pytestconfig.getoption("native_q") or "").strip()
    local_q = str(pytestconfig.getoption("local_q") or "").strip()
    global_q = str(pytestconfig.getoption("global_q") or "").strip()
    graph_entity = str(pytestconfig.getoption("graph_entity") or "").strip()

    print_enabled = bool(pytestconfig.getoption("print_results"))

    rm = RetrievalManager(milvus_collection_name=milvus_collection or None)

    if keyword_q:
        print("\n[Keyword] query=", repr(keyword_q))
        res = rm.keyword(group_id=group_id, query=keyword_q, top_k=10, rerank_enabled=False)
        print("[Keyword] hits=", len(res.keyword_hits))
        for i, h in enumerate(res.keyword_hits[:5]):
            print(f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} index={h.index} text={repr((h.text or '')[:160])}")
        _maybe_print_result(title="Keyword", res=res, enabled=print_enabled)

    if semantic_q:
        if not milvus_collection:
            pytest.skip("Missing --milvus-collection for semantic retrieval")
        if not milvus_collection_valid:
            pytest.skip(
                "Invalid --milvus-collection value; Milvus collection name must start with a letter or underscore. "
                "If you copied a numeric id from UI, pass the actual collection name instead."
            )
        print("\n[Semantic] query=", repr(semantic_q))
        res = rm.native(group_id=group_id, query=semantic_q, top_k=10, rerank_enabled=False)
        print("[Semantic] hits=", len(res.semantic_hits))
        for i, h in enumerate(res.semantic_hits[:5]):
            print(
                f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} "
                f"score={getattr(h, 'score', None)} doc_time={getattr(h, 'doc_time', None)} "
                f"text={repr((h.text or '')[:160])}"
            )
        _maybe_print_result(title="Semantic", res=res, enabled=print_enabled)

    if native_q:
        if not milvus_collection:
            pytest.skip("Missing --milvus-collection for native retrieval")
        if not milvus_collection_valid:
            pytest.skip(
                "Invalid --milvus-collection value; Milvus collection name must start with a letter or underscore. "
                "If you copied a numeric id from UI, pass the actual collection name instead."
            )
        print("\n[Native] query=", repr(native_q))
        res = rm.native(group_id=group_id, query=native_q, top_k=10, rerank_enabled=False)
        print("[Native] semantic_hits=", len(res.semantic_hits))
        for i, h in enumerate(res.semantic_hits[:5]):
            print(
                f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} "
                f"score={getattr(h, 'score', None)} doc_time={getattr(h, 'doc_time', None)} "
                f"text={repr((h.text or '')[:160])}"
            )

    if graph_entity:
        print("\n[Graph] entity_name=", repr(graph_entity))
        res = rm.local(
            group_id=group_id,
            query=graph_entity,
            graph_entity_name=graph_entity,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
        )
        if res.local_graph is None:
            print("[Graph] local_graph=None")
        else:
            print("[Graph] nodes=", len(res.local_graph.nodes), "edges=", len(res.local_graph.edges))
            for i, n in enumerate(res.local_graph.nodes[:8]):
                print(
                    f"  - {i}: name={repr(n.get('name'))} type={repr(n.get('type'))} desc={repr((n.get('description') or '')[:160])}"
                )
        _maybe_print_result(title="Graph", res=res, enabled=print_enabled)

    if local_q:
        if not graph_entity:
            pytest.skip("Missing --graph-entity for local graph retrieval")
        print("\n[Local] query=", repr(local_q), "graph_entity=", repr(graph_entity))
        res = rm.local(
            group_id=group_id,
            query=local_q,
            graph_entity_name=graph_entity,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
        )
        if res.local_graph is None:
            print("[Local] local_graph=None")
        else:
            print("[Local] nodes=", len(res.local_graph.nodes), "edges=", len(res.local_graph.edges))
        _maybe_print_result(title="Local", res=res, enabled=print_enabled)

    if global_q:
        if not graph_entity:
            pytest.skip("Missing --graph-entity for global graph retrieval")
        print("\n[Global] query=", repr(global_q), "graph_entity=", repr(graph_entity))
        res = rm.global_(
            group_id=group_id,
            query=global_q,
            graph_entity_name=graph_entity,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
        )
        if res.global_graph is None:
            print("[Global] global_graph=None")
        else:
            print("[Global] nodes=", len(res.global_graph.nodes), "edges=", len(res.global_graph.edges))
        _maybe_print_result(title="Global", res=res, enabled=print_enabled)

    if not (keyword_q or semantic_q or native_q or local_q or global_q or graph_entity):
        pytest.skip("No query provided: pass --keyword-q and/or --semantic-q and/or --graph-entity")
