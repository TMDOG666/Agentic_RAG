from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import ChunkRecord, DocumentRecord, GraphEntityRecord, GraphRelationRecord

from grag.config import get_config_manager
from grag.data_client import get_data_manager


def _cleanup_postgres(*, group_id: str, doc_id: str) -> None:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
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


class TestPostgresGraphRepositoryRealDB:
    def test_real_connection_and_upsert_and_cleanup(self) -> None:
        get_config_manager().initialize()
        dm = get_data_manager()

        assert dm.get_postgres_client().test_connection() is True

        repo = PostgresGraphRepository(dm.get_postgres_client())

        group_id = "smoke"
        doc_id = "smoke::realdb_pg"
        try:
            doc = DocumentRecord(
                group_id=group_id,
                doc_id=doc_id,
                doc_name="realdb_pg",
                doc_time="now",
                metadata={"source": "real_db_test"},
            )
            chunks = [
                ChunkRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}::chunk_0",
                    index=0,
                    text="hello",
                )
            ]
            entities = [
                GraphEntityRecord(
                    entity_id=f"{group_id}:{doc_id}:e0",
                    group_id=group_id,
                    doc_id=doc_id,
                    canonical_name="张三",
                    type="人物",
                    aliases=["张三"],
                    description="desc",
                )
            ]
            relations = [
                GraphRelationRecord(
                    relation_id=f"{group_id}:{doc_id}:r0",
                    group_id=group_id,
                    doc_id=doc_id,
                    subject="张三",
                    object="张三",
                    relation_type="self",
                    description="desc",
                    confidence=8,
                )
            ]
            repo.upsert_document_and_chunks(document=doc, chunks=chunks, entities=entities, relations=relations)
        finally:
            _cleanup_postgres(group_id=group_id, doc_id=doc_id)
