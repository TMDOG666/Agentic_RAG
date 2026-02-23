import os
from pathlib import Path
import time

from datetime import datetime, timezone

import pytest

project_root = Path(__file__).parent.parent.parent.parent

from grag.config import ProviderType, get_grag_settings, initialize_config
from grag.data_client import get_data_manager
from grag.graph_construction.graph_builder import GraphBuilder
from grag.preprocessing.preprocessing_manager import PreprocessingManager
from grag.storage.storage_impl import DataClientGraphStorage


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(x in url_lower for x in ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"])


def _ensure_real_llm_embedding_ready() -> None:
    settings = get_grag_settings()

    llm_cfg = settings.get_provider_config(ProviderType.LLM)
    llm_api_key = os.environ.get("GRAG_LLM_API_KEY") or os.environ.get(getattr(llm_cfg, "api_key_env", "") or "")
    if not llm_api_key and llm_cfg.base_url and not _is_local_url(llm_cfg.base_url):
        pytest.skip("LLM API key missing for non-local base_url")

    emb_cfg = settings.get_provider_config(ProviderType.EMBEDDING)
    emb_api_key = os.environ.get("GRAG_EMBEDDING_API_KEY")
    api_key_env = getattr(emb_cfg, "api_key_env", None)
    if api_key_env:
        emb_api_key = emb_api_key or os.environ.get(api_key_env)
    if not emb_api_key and emb_cfg.base_url and not _is_local_url(emb_cfg.base_url):
        pytest.skip("Embedding API key missing for non-local base_url")


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
    if pymilvus.utility.has_collection(collection_name, using=milvus._alias):
        pymilvus.utility.drop_collection(collection_name, using=milvus._alias)


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
def test_real_docs_end_to_end_ingestion_with_real_llm_embedding(request) -> None:
    initialize_config()

    try:
        __import__("docx")
    except ImportError as e:
        pytest.skip(f"python-docx missing: {e}")

    _ensure_real_llm_embedding_ready()

    dm = get_data_manager()
    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    input_dir = project_root / "test" / "grag" / "test_data" / "input"
    files = sorted([p for p in input_dir.iterdir() if p.is_file()])
    assert len(files) == 2

    group_id = "real_docs"
    processor = PreprocessingManager()
    milvus_collection_name = f"grag_test_{group_id}"
    storage = DataClientGraphStorage(
        milvus_collection_name=milvus_collection_name,
        milvus_upsert_strategy="delete_then_insert",
    )
    builder = GraphBuilder(storage=storage)

    doc_ids: list[str] = []
    all_chunk_ids: list[str] = []

    try:
        for p in files:
            text = processor.process_file(p, use_llm=True)
            assert isinstance(text, str) and len(text.strip()) > 0

            doc_time = datetime.now(timezone.utc).isoformat()
            doc_id = f"real_{abs(hash(p.name))}"
            doc_ids.append(doc_id)

            result = builder.build_and_save(
                text=text,
                doc_time=doc_time,
                doc_name=p.name,
                group_id=group_id,
                doc_id=doc_id,
            )

            assert result.document.group_id == group_id
            assert result.document.doc_id == doc_id
            assert result.document.doc_name == p.name
            assert result.document.doc_time == doc_time

            assert len(result.chunks) > 0
            assert len(result.embeddings) == len(result.chunks)

            chunk_ids = [c.chunk_id for c in result.chunks]
            all_chunk_ids.extend(chunk_ids)

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

            milvus = dm.get_milvus_client()
            milvus.connect()
            pymilvus = __import__("pymilvus")
            col = pymilvus.Collection(name=milvus_collection_name, using=milvus._alias)
            pks = [f"{group_id}:{cid}" for cid in chunk_ids]
            expr = 'pk in ["' + '", "'.join(pks) + '"]'
            rows = col.query(expr=expr, output_fields=["pk", "doc_time"], limit=len(pks))
            assert len(rows) == len(pks)
            assert all(r.get("doc_time") == doc_time for r in rows)

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
        pause_seconds = int(request.config.getoption("--pause"))
        if pause_seconds > 0:
            time.sleep(pause_seconds)

        if bool(request.config.getoption("--no-cleanup")):
            return

        if all_chunk_ids:
            _cleanup_milvus(
                collection_name=milvus_collection_name,
                group_id=group_id,
                chunk_ids=all_chunk_ids,
            )
        _cleanup_milvus_graph_index(collection_name="grag_graph_index", group_id=group_id, doc_ids=doc_ids)
        _drop_milvus_collection(collection_name=milvus_collection_name)
        for doc_id in doc_ids:
            _cleanup_neo4j(group_id=group_id, doc_id=doc_id)
        if doc_ids:
            _cleanup_postgres(group_id=group_id, doc_ids=doc_ids)
