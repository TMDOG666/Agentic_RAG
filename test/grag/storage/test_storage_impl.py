from datetime import datetime, timezone

from grag.storage.storage_impl import DataClientGraphStorage
from grag.storage.types import (
    ChunkEmbeddingRecord,
    ChunkRecord,
    DocumentRecord,
    GraphEntityRecord,
    GraphRelationRecord,
)

from grag.config import initialize_config
from grag.data_client import get_data_manager


def _cleanup_real_storage(*, group_id: str, doc_id: str, chunk_ids: list[str]) -> None:
    dm = get_data_manager()

    # Postgres
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
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

    # Milvus
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    col = pymilvus.Collection(name=milvus.get_collection_name(), using=milvus._alias)
    pks = [f"{group_id}:{cid}" for cid in chunk_ids]
    expr = 'pk in ["' + '", "'.join(pks) + '"]'
    col.delete(expr)
    col.flush()

    # Neo4j
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


class TestDataClientGraphStorageRealDB:
    def test_real_connection_write_and_cleanup(self) -> None:
        initialize_config()
        dm = get_data_manager()

        assert dm.get_postgres_client().test_connection() is True
        assert dm.get_milvus_client().test_connection() is True
        assert dm.get_neo4j_client().test_connection() is True

        storage = DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert")

        now = datetime.now(timezone.utc).isoformat()
        group_id = "smoke"
        doc_id = f"smoke::realdb_storage::{int(datetime.now(timezone.utc).timestamp())}"
        chunk_ids = [f"{doc_id}::chunk_0", f"{doc_id}::chunk_1"]

        document = DocumentRecord(
            group_id=group_id,
            doc_id=doc_id,
            doc_name="realdb_storage",
            doc_time=now,
            metadata={"source": "real_db_test"},
        )
        chunks = [
            ChunkRecord(group_id=group_id, doc_id=doc_id, chunk_id=chunk_ids[0], index=0, text="a"),
            ChunkRecord(group_id=group_id, doc_id=doc_id, chunk_id=chunk_ids[1], index=1, text="b"),
        ]
        embeddings = [
            ChunkEmbeddingRecord(group_id=group_id, doc_id=doc_id, chunk_id=chunk_ids[0], vector=[0.1, 0.2]),
            ChunkEmbeddingRecord(group_id=group_id, doc_id=doc_id, chunk_id=chunk_ids[1], vector=[0.3, 0.4]),
        ]
        entities = [
            GraphEntityRecord(
                group_id=group_id,
                doc_id=doc_id,
                canonical_name="张三",
                type="人物",
                aliases=["张三"],
                description="real_db_test",
            )
        ]
        relations = [
            GraphRelationRecord(
                group_id=group_id,
                doc_id=doc_id,
                subject="张三",
                object="张三",
                relation_type="self",
                description="real_db_test",
                confidence=8,
            )
        ]

        try:
            storage.save_document(
                document=document,
                chunks=chunks,
                embeddings=embeddings,
                entities=entities,
                relations=relations,
            )
        finally:
            _cleanup_real_storage(group_id=group_id, doc_id=doc_id, chunk_ids=chunk_ids)
