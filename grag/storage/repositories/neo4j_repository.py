from __future__ import annotations

from typing import Sequence

from grag.data_client.neo4j_client import Neo4jClient

from ..types import DocumentRecord, GraphEntityRecord, GraphRelationRecord


"""grag.storage.repositories.neo4j_repository

Neo4j 图存储仓储层（Repository）。

定位：
- 本模块只负责将“融合后的实体/关系”写入图数据库（Neo4j）。
- 不负责关系型元信息（Postgres）与向量（Milvus）。

图模型约定（最小可用）：
- (:Document {group_id, doc_id})
  - 属性：doc_name/doc_time

- (:Entity {group_id, doc_id, name})
  - 属性：type/description/aliases
  - 说明：这里的 `name` 是 canonical_name（融合后的标准实体名）

- 关系：
  - (s:Entity)-[:REL {group_id, doc_id, type, description, confidence}]->(o:Entity)
  - 说明：这里的 `type` 是 relation_type（例如 friend/owns/located_in 等）

幂等策略：
- 节点使用 MERGE 确保幂等。
- 关系同样使用 MERGE，但当前 MERGE key 包含 (group_id, doc_id, type, description)，
  因此对“同一对实体”存在多条不同描述的关系时会产生多条边；这是有意的最小实现。
"""


class Neo4jGraphRepository:
    """Neo4j 图谱落库仓储。

    依赖：
    - `Neo4jClient` 负责读取配置与创建 driver

    事务语义：
    - 使用 `session.execute_write`，保证写入在单个写事务中执行。

    注意：
    - 当前实现假设 relations 的 subject/object 对应的实体在同一次写入中已 MERGE。
      如果 relations 指向不存在的实体名，将导致 MATCH 为空从而不创建边。
    """

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client
        self._constraints_initialized = False

    def ensure_constraints(self) -> None:
        """确保必要的约束存在。

        说明：
        - 这里仅作为开发期辅助；生产建议使用 migrations 管理。
        - 当前方法未在 upsert_graph 内部强制调用（由上层决定何时执行）。
        """
        if self._constraints_initialized:
            return

        driver = self._client.get_driver()
        db = self._get_database()

        def _run(session):
            try:
                session.run(
                    "CREATE CONSTRAINT grag_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.group_id, e.doc_id, e.name) IS UNIQUE"
                )
            except Exception:
                session.run(
                    "CREATE CONSTRAINT grag_entity_key IF NOT EXISTS ON (e:Entity) ASSERT (e.group_id, e.doc_id, e.name) IS UNIQUE"
                )

        if db:
            with driver.session(database=db) as session:
                _run(session)
        else:
            with driver.session() as session:
                _run(session)

        self._constraints_initialized = True

    def _get_database(self):
        try:
            return self._client._get_config().database
        except Exception:
            return None

    def upsert_graph(
        self,
        *,
        document: DocumentRecord,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> None:
        """将文档、实体、关系写入 Neo4j。

        Args:
            document:
                文档节点信息。

            entities:
                canonical entities（融合后的标准实体）。

            relations:
                rewritten relations（subject/object 已 canonical 化）。

        副作用：
        - MERGE Document 节点
        - MERGE Entity 节点
        - MERGE Entity->Entity 关系

        失败语义：
        - driver/session/tx 执行异常将向上抛出。
        """
        self.ensure_constraints()

        driver = self._client.get_driver()
        db = self._get_database()

        def _run(tx):
            tx.run(
                "MERGE (d:Document {group_id: $group_id, doc_id: $doc_id}) "
                "SET d.doc_name=$doc_name, d.doc_time=$doc_time",
                group_id=document.group_id,
                doc_id=document.doc_id,
                doc_name=document.doc_name,
                doc_time=document.doc_time,
            )

            for e in entities:
                tx.run(
                    "MERGE (n:Entity {group_id: $group_id, doc_id: $doc_id, name: $name}) "
                    "SET n.type=$type, n.description=$description, n.aliases=$aliases",
                    group_id=e.group_id,
                    doc_id=e.doc_id,
                    name=e.canonical_name,
                    type=e.type,
                    description=e.description,
                    aliases=list(e.aliases),
                )

            for r in relations:
                tx.run(
                    "MATCH (s:Entity {group_id: $group_id, doc_id: $doc_id, name: $s}) "
                    "MATCH (o:Entity {group_id: $group_id, doc_id: $doc_id, name: $o}) "
                    "MERGE (s)-[rel:REL {group_id: $group_id, doc_id: $doc_id, type: $t, description: $d}]->(o) "
                    "SET rel.confidence = $c",
                    group_id=r.group_id,
                    doc_id=r.doc_id,
                    s=r.subject,
                    o=r.object,
                    t=r.relation_type,
                    d=r.description,
                    c=r.confidence,
                )

        if db:
            with driver.session(database=db) as session:
                session.execute_write(_run)
        else:
            with driver.session() as session:
                session.execute_write(_run)
