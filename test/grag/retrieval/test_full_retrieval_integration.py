from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
import time

import pytest
from typing import Optional

from grag.config import initialize_config
from grag.data_client import get_data_manager
from grag.graph_construction.graph_builder import GraphBuilder
from grag.retrieval import RetrievalManager
from grag.storage.storage_impl import DataClientGraphStorage


def _cleanup_postgres(*, group_id: str, doc_ids: list[str]) -> None:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for doc_id in doc_ids:
                    cur.execute(
                        "DELETE FROM grag_entities WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_chunks WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_documents WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
    finally:
        conn.close()


def _cleanup_milvus(*, collection_name: str, group_id: str, chunk_ids: list[str]) -> None:
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    col = pymilvus.Collection(name=collection_name, using=milvus._alias)
    pks = [f"{group_id}:{cid}" for cid in chunk_ids]
    expr = 'pk in ["' + '", "'.join(pks) + '"]'
    col.delete(expr)
    col.flush()


def _drop_milvus_collection(*, collection_name: str) -> None:
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    try:
        pymilvus.utility.drop_collection(collection_name)
    except Exception:
        pass


def _cleanup_neo4j(*, group_id: str, doc_id: str) -> None:
    dm = get_data_manager()
    driver = dm.get_neo4j_client().get_driver()

    def _run(tx):
        tx.run(
            "MATCH (e:Entity {group_id: $group_id, doc_id: $doc_id}) DETACH DELETE e",
            group_id=group_id,
            doc_id=doc_id,
        )
        tx.run(
            "MATCH (d:Document {group_id: $group_id, doc_id: $doc_id}) DETACH DELETE d",
            group_id=group_id,
            doc_id=doc_id,
        )

    db = None
    try:
        db = dm.get_neo4j_client()._get_config().database
    except Exception:
        db = None

    if db:
        with driver.session(database=db) as session:
            session.execute_write(_run)
    else:
        with driver.session() as session:
            session.execute_write(_run)


def _pick_keyword_query(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "检索"

    # 关键词检索当前使用的是 Postgres ILIKE '%query%'（连续子串匹配）。
    # 因此这里必须挑选“原文中存在的连续片段”，否则会出现入库成功但 keyword 命中为空的假失败。
    for line in t.splitlines():
        s = line.strip()
        if s:
            return s[:12]
    return t[:12]


def _pick_semantic_query(text: str) -> str:
    return (text or "")[:32].strip() or "这份文档讲了什么"


def _pick_graph_entity_name(*, group_id: str, doc_id: str) -> Optional[str]:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT canonical_name FROM grag_entities WHERE group_id=%s AND doc_id=%s LIMIT 1",
                    (group_id, doc_id),
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


@pytest.mark.integration
def test_full_retrieval_with_real_db(real_doc_texts, pytestconfig) -> None:
    initialize_config()
    dm = get_data_manager()

    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    group_id = f"pytest_ret_{uuid4().hex[:8]}"
    collection_name = f"pytest_ret_{uuid4().hex[:10]}"

    pause_s = float(pytestconfig.getoption("pause") or 0)
    no_cleanup = bool(pytestconfig.getoption("no_cleanup"))

    storage = DataClientGraphStorage(
        milvus_collection_name=collection_name,
        milvus_upsert_strategy="delete_then_insert",
    )
    builder = GraphBuilder(storage=storage)

    created_doc_ids: list[str] = []
    created_chunk_ids: list[str] = []

    try:
        assert len(real_doc_texts) >= 2

        # 1) 入库两篇文档（写入 Postgres + Milvus + Neo4j）
        first_doc_id: Optional[str] = None
        example_chunk_text: str = ""

        for i, (p, text) in enumerate(real_doc_texts[:2]):
            doc_id = f"doc_{i}_{uuid4().hex[:8]}"
            doc_name = p.stem
            doc_time = datetime.now(timezone.utc).isoformat()
            snippet = (text or "")[:6000]

            result = builder.build_and_save(
                text=snippet,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
            )

            created_doc_ids.append(doc_id)
            created_chunk_ids.extend([c.chunk_id for c in result.chunks])

            assert result.document.group_id == group_id
            assert result.document.doc_id == doc_id
            assert len(result.chunks) > 0

            if first_doc_id is None:
                first_doc_id = doc_id
                example_chunk_text = result.chunks[0].text or ""

        assert first_doc_id is not None

        # 2) 真实检索：keyword/semantic/graph
        rm = RetrievalManager(milvus_collection_name=collection_name)

        keyword_q = _pick_keyword_query(example_chunk_text)
        print("\n[Keyword] query=", repr(keyword_q))
        keyword_res = rm.search(
            group_id=group_id,
            query=keyword_q,
            modes=["keyword"],
            top_k=10,
            rerank_enabled=False,
        )
        print("[Keyword] hits=", len(keyword_res.keyword_hits))
        for i, h in enumerate(keyword_res.keyword_hits[:3]):
            print(
                f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} index={h.index} text={repr((h.text or '')[:120])}"
            )
        assert isinstance(keyword_res.keyword_hits, list)
        assert len(keyword_res.keyword_hits) > 0
        assert all(h.group_id == group_id for h in keyword_res.keyword_hits)
        assert any(keyword_q.strip() in (h.text or "") for h in keyword_res.keyword_hits)

        semantic_q = _pick_semantic_query(example_chunk_text)
        print("\n[Semantic] query=", repr(semantic_q))
        semantic_res = rm.search(
            group_id=group_id,
            query=semantic_q,
            modes=["semantic"],
            top_k=10,
            rerank_enabled=False,
        )
        print("[Semantic] hits=", len(semantic_res.semantic_hits))
        for i, h in enumerate(semantic_res.semantic_hits[:3]):
            print(
                f"  - {i}: doc_id={h.doc_id} chunk_id={h.chunk_id} score={getattr(h, 'score', None)} doc_time={getattr(h, 'doc_time', None)} text={repr((h.text or '')[:120])}"
            )
        assert isinstance(semantic_res.semantic_hits, list)
        assert len(semantic_res.semantic_hits) > 0
        assert all(h.group_id == group_id for h in semantic_res.semantic_hits)

        entity_name = _pick_graph_entity_name(group_id=group_id, doc_id=first_doc_id)
        if entity_name:
            print("\n[Graph] entity_name=", repr(entity_name))
            graph_res = rm.search(
                group_id=group_id,
                query=entity_name,
                modes=["graph"],
                graph_entity_name=entity_name,
                graph_max_depth=2,
                graph_limit=50,
            )
            assert graph_res.graph is not None
            print("[Graph] nodes=", len(graph_res.graph.nodes), "edges=", len(graph_res.graph.edges))
            for i, n in enumerate(graph_res.graph.nodes[:5]):
                print(
                    f"  - {i}: name={repr(n.get('name'))} type={repr(n.get('type'))} desc={repr((n.get('description') or '')[:120])}"
                )
            assert graph_res.graph is not None
            assert isinstance(graph_res.graph.nodes, list)
            assert isinstance(graph_res.graph.edges, list)
        else:
            pytest.skip("No entity extracted for graph retrieval in this run")

    finally:
        if pause_s > 0:
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
