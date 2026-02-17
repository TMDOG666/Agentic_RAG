import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import ChunkRecord, DocumentRecord, GraphEntityRecord

from grag.config import initialize_config
from grag.data_client import get_data_manager


def _cleanup_postgres(*, group_id: str, doc_id: str) -> None:
    dm = get_data_manager()
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


class TestPostgresGraphRepositoryRealDB:
    def test_real_connection_and_upsert_and_cleanup(self) -> None:
        initialize_config()
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
                    group_id=group_id,
                    doc_id=doc_id,
                    canonical_name="张三",
                    type="人物",
                    aliases=["张三"],
                    description="desc",
                )
            ]
            repo.upsert_document_and_chunks(document=doc, chunks=chunks, entities=entities)
        finally:
            _cleanup_postgres(group_id=group_id, doc_id=doc_id)


def run_real_db_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 PostgresGraphRepository (REAL DB)")
    print("=" * 60)
    t = TestPostgresGraphRepositoryRealDB()
    t.test_real_connection_and_upsert_and_cleanup()


def run_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 PostgresGraphRepository (REAL DB)")
    print("=" * 60)
    try:
        run_real_db_tests()
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        raise


if __name__ == "__main__":
    run_tests()
