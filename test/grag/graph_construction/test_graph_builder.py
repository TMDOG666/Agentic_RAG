from pathlib import Path

from datetime import datetime, timezone
import time
from uuid import uuid4

from grag.graph_construction.graph_builder import GraphBuilder
from grag.graph_construction.graph_construction_manager import GraphConstructionManager
from grag.storage.storage_impl import DataClientGraphStorage
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import ChunkRecord, DocumentRecord, GraphEntityRecord

from grag.config import initialize_config
from grag.data_client import get_data_manager
import pytest


def _cleanup_postgres(*, group_id: str, doc_ids: list[str]) -> None:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for doc_id in doc_ids:
                    cur.execute(
                        "DELETE FROM grag_relations WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
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


def _cleanup_milvus_graph_index(*, collection_name: str, group_id: str, doc_ids: list[str]) -> None:
    """清理 graph_index collection 中本次写入的 entity/relation 向量记录。"""
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    if not pymilvus.utility.has_collection(collection_name, using=milvus._alias):
        return
    col = pymilvus.Collection(name=collection_name, using=milvus._alias)
    for doc_id in doc_ids:
        expr = f'group_id == "{group_id}" and doc_id == "{doc_id}"'
        try:
            col.delete(expr)
        except Exception:
            pass
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


@pytest.mark.integration
def test_graph_builder_build_and_save_with_real_db(real_doc_texts, pytestconfig) -> None:
    initialize_config()
    dm = get_data_manager()

    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    group_id = f"pytest_gb_{uuid4().hex[:8]}"
    collection_name = f"pytest_gb_{uuid4().hex[:10]}"

    storage = DataClientGraphStorage(
        milvus_collection_name=collection_name,
        milvus_upsert_strategy="delete_then_insert",
    )
    builder = GraphBuilder(storage=storage)

    pause_s = float(pytestconfig.getoption("pause") or 0)
    no_cleanup = bool(pytestconfig.getoption("no_cleanup"))

    created_doc_ids: list[str] = []
    created_chunk_ids: list[str] = []
    try:
        assert len(real_doc_texts) >= 2

        for i, (p, text) in enumerate(real_doc_texts[:2]):
            doc_id = f"doc_{i}_{uuid4().hex[:8]}"
            doc_name = p.stem
            doc_time = datetime.now(timezone.utc).isoformat()
            snippet = text[:6000]

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
            assert len(result.embeddings) == len(result.chunks)
            assert all(c.chunk_id.startswith(f"{doc_id}::chunk_") for c in result.chunks)

            # Postgres：doc_time 应写入 grag_documents
            conn = dm.get_postgres_client().get_connection()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT doc_time FROM grag_documents WHERE group_id=%s AND doc_id=%s",
                            (group_id, doc_id),
                        )
                        row = cur.fetchone()
                        assert row is not None
                        assert row[0] == doc_time
            finally:
                conn.close()

            # Milvus：doc_time 应写入向量记录，且可作为 output_fields 被读取
            milvus = dm.get_milvus_client()
            milvus.connect()
            pymilvus = __import__("pymilvus")
            col = pymilvus.Collection(name=collection_name, using=milvus._alias)
            pks = [f"{group_id}:{cid}" for cid in [c.chunk_id for c in result.chunks]]
            expr = 'pk in ["' + '", "'.join(pks) + '"]'
            rows = col.query(expr=expr, output_fields=["pk", "doc_time"], limit=len(pks))
            assert len(rows) == len(pks)
            assert all(r.get("doc_time") == doc_time for r in rows)

            # Neo4j：Document 节点应包含 doc_time
            driver = dm.get_neo4j_client().get_driver()

            def _read_doc_time(tx):
                return tx.run(
                    "MATCH (d:Document {group_id: $group_id, doc_id: $doc_id}) RETURN d.doc_time AS doc_time",
                    group_id=group_id,
                    doc_id=doc_id,
                ).single()

            db = None
            try:
                db = dm.get_neo4j_client()._get_config().database
            except Exception:
                db = None

            if db:
                with driver.session(database=db) as session:
                    rec = session.execute_read(_read_doc_time)
            else:
                with driver.session() as session:
                    rec = session.execute_read(_read_doc_time)
            assert rec is not None
            assert rec.get("doc_time") == doc_time
    finally:
        if pause_s > 0:
            time.sleep(pause_s)

        if no_cleanup:
            return

        # 清理：新写入的三库数据
        if created_chunk_ids:
            _cleanup_milvus(collection_name=collection_name, group_id=group_id, chunk_ids=created_chunk_ids)

        # graph_index 默认 collection 名为 grag_graph_index（见 DataClientGraphStorage 默认值）。
        _cleanup_milvus_graph_index(collection_name="grag_graph_index", group_id=group_id, doc_ids=created_doc_ids)

        for doc_id in created_doc_ids:
            _cleanup_neo4j(group_id=group_id, doc_id=doc_id)
        if created_doc_ids:
            _cleanup_postgres(group_id=group_id, doc_ids=created_doc_ids)
        _drop_milvus_collection(collection_name=collection_name)
