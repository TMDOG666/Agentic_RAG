from __future__ import annotations

import pytest

from grag.config import initialize_config
from grag.data_client import get_data_manager
from grag.retrieval import RetrievalManager


@pytest.mark.integration
def test_query_only_retrieval(pytestconfig) -> None:
    """只测试“查询/检索”模块：不做入库、不做抽取。

    使用方式：
    - 你需要提前准备好一份已经入库的数据（Postgres/Milvus/Neo4j）。
    - 运行本用例时通过 pytest options 传入 group_id、milvus collection 以及 query。
    """

    initialize_config()
    dm = get_data_manager()

    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    group_id = str(pytestconfig.getoption("group_id") or "").strip()
    milvus_collection = str(pytestconfig.getoption("milvus_collection") or "").strip()

    if not group_id:
        pytest.skip("Missing --group-id; this test only validates query path against existing data")

    keyword_q = str(pytestconfig.getoption("keyword_q") or "").strip()
    semantic_q = str(pytestconfig.getoption("semantic_q") or "").strip()
    graph_entity = str(pytestconfig.getoption("graph_entity") or "").strip()

    rm = RetrievalManager(milvus_collection_name=milvus_collection or None)

    if keyword_q:
        print("\n[Keyword] query=", repr(keyword_q))
        res = rm.search(group_id=group_id, query=keyword_q, modes=["keyword"], top_k=10, rerank_enabled=False)
        print("[Keyword] hits=", len(res.keyword_hits))
        for i, h in enumerate(res.keyword_hits[:5]):
            print(f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} index={h.index} text={repr((h.text or '')[:160])}")

    if semantic_q:
        if not milvus_collection:
            pytest.skip("Missing --milvus-collection for semantic retrieval")
        print("\n[Semantic] query=", repr(semantic_q))
        res = rm.search(group_id=group_id, query=semantic_q, modes=["semantic"], top_k=10, rerank_enabled=False)
        print("[Semantic] hits=", len(res.semantic_hits))
        for i, h in enumerate(res.semantic_hits[:5]):
            print(f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} index={h.index} text={repr((h.text or '')[:160])}")

    if graph_entity:
        print("\n[Graph] entity_name=", repr(graph_entity))
        res = rm.search(
            group_id=group_id,
            query=graph_entity,
            modes=["graph"],
            graph_entity_name=graph_entity,
            graph_max_depth=2,
            graph_limit=50,
            rerank_enabled=False,
        )
        if res.graph is None:
            print("[Graph] graph=None")
        else:
            print("[Graph] nodes=", len(res.graph.nodes), "edges=", len(res.graph.edges))
            for i, n in enumerate(res.graph.nodes[:8]):
                print(
                    f"  - {i}: name={repr(n.get('name'))} type={repr(n.get('type'))} desc={repr((n.get('description') or '')[:160])}"
                )

    if not (keyword_q or semantic_q or graph_entity):
        pytest.skip("No query provided: pass --keyword-q and/or --semantic-q and/or --graph-entity")
