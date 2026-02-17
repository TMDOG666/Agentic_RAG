import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.types import ChunkEmbeddingRecord, DocumentRecord

from grag.config import initialize_config
from grag.data_client import get_data_manager


def _cleanup_milvus(*, group_id: str, chunk_ids: list[str]) -> None:
    dm = get_data_manager()
    client = dm.get_milvus_client()
    client.connect()

    pymilvus = __import__("pymilvus")
    col = pymilvus.Collection(name=client.get_collection_name(), using=client._alias)

    pks = [f"{group_id}:{cid}" for cid in chunk_ids]
    expr = 'pk in ["' + '", "'.join(pks) + '"]'
    col.delete(expr)
    col.flush()


class TestMilvusVectorRepositoryRealDB:
    def test_real_connection_and_upsert_and_cleanup(self) -> None:
        initialize_config()
        dm = get_data_manager()

        assert dm.get_milvus_client().test_connection() is True

        repo = MilvusVectorRepository(
            dm.get_milvus_client(),
            upsert_strategy="delete_then_insert",
        )

        group_id = "smoke"
        doc_id = "smoke::realdb_milvus"
        chunk_ids = [f"{doc_id}::chunk_0", f"{doc_id}::chunk_1"]

        try:
            doc = DocumentRecord(
                group_id=group_id,
                doc_id=doc_id,
                doc_name="realdb_milvus",
                doc_time="now",
                metadata={"source": "real_db_test"},
            )
            embeddings = [
                ChunkEmbeddingRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=chunk_ids[0],
                    vector=[0.1, 0.2],
                ),
                ChunkEmbeddingRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    chunk_id=chunk_ids[1],
                    vector=[0.3, 0.4],
                ),
            ]
            repo.upsert_chunk_embeddings(document=doc, embeddings=embeddings)
        finally:
            _cleanup_milvus(group_id=group_id, chunk_ids=chunk_ids)


def run_real_db_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 MilvusVectorRepository (REAL DB)")
    print("=" * 60)
    t = TestMilvusVectorRepositoryRealDB()
    t.test_real_connection_and_upsert_and_cleanup()


def run_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 MilvusVectorRepository (REAL DB)")
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
