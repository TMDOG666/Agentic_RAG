import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.types import DocumentRecord, GraphEntityRecord, GraphRelationRecord

from grag.config import initialize_config
from grag.data_client import get_data_manager


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


class TestNeo4jGraphRepositoryRealDB:
    def test_real_connection_and_upsert_and_cleanup(self) -> None:
        initialize_config()
        dm = get_data_manager()

        assert dm.get_neo4j_client().test_connection() is True

        repo = Neo4jGraphRepository(dm.get_neo4j_client())

        group_id = "smoke"
        doc_id = "smoke::realdb_neo4j"
        try:
            doc = DocumentRecord(
                group_id=group_id,
                doc_id=doc_id,
                doc_name="realdb_neo4j",
                doc_time="now",
                metadata={"source": "real_db_test"},
            )
            entities = [
                GraphEntityRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    canonical_name="张三",
                    type="人物",
                    aliases=["张三"],
                    description="desc",
                ),
                GraphEntityRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    canonical_name="李四",
                    type="人物",
                    aliases=["李四"],
                    description="desc",
                ),
            ]
            relations = [
                GraphRelationRecord(
                    group_id=group_id,
                    doc_id=doc_id,
                    subject="张三",
                    object="李四",
                    relation_type="friend",
                    description="real_db_test",
                    confidence=8,
                )
            ]
            repo.upsert_graph(document=doc, entities=entities, relations=relations)
        finally:
            _cleanup_neo4j(group_id=group_id, doc_id=doc_id)


def run_real_db_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 Neo4jGraphRepository (REAL DB)")
    print("=" * 60)
    t = TestNeo4jGraphRepositoryRealDB()
    t.test_real_connection_and_upsert_and_cleanup()


def run_tests() -> None:
    print("\n" + "=" * 60)
    print("开始测试 Neo4jGraphRepository (REAL DB)")
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
