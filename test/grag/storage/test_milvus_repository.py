from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.types import ChunkEmbeddingRecord, DocumentRecord

from grag.config import get_config_manager
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
        get_config_manager().initialize()
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
