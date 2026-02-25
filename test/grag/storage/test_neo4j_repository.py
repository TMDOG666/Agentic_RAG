from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.types import DocumentRecord, GraphEntityRecord, GraphRelationRecord

from grag.config import get_config_manager
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
        get_config_manager().initialize()
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
                    entity_id=f"{group_id}:{doc_id}:e0",
                    group_id=group_id,
                    doc_id=doc_id,
                    canonical_name="张三",
                    type="人物",
                    aliases=["张三"],
                    description="desc",
                ),
                GraphEntityRecord(
                    entity_id=f"{group_id}:{doc_id}:e1",
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
                    relation_id=f"{group_id}:{doc_id}:r0",
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
