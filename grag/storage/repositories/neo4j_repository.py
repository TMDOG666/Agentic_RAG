from __future__ import annotations

from typing import Optional, Sequence

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
                    "SET n.entity_id=$entity_id, n.type=$type, n.description=$description, n.aliases=$aliases",
                    group_id=e.group_id,
                    doc_id=e.doc_id,
                    name=e.canonical_name,
                    entity_id=e.entity_id,
                    type=e.type,
                    description=e.description,
                    aliases=list(e.aliases),
                )

            for r in relations:
                tx.run(
                    "MATCH (s:Entity {group_id: $group_id, doc_id: $doc_id, name: $s}) "
                    "MATCH (o:Entity {group_id: $group_id, doc_id: $doc_id, name: $o}) "
                    "MERGE (s)-[rel:REL {group_id: $group_id, doc_id: $doc_id, relation_id: $rid}]->(o) "
                    "SET rel.type=$t, rel.description=$d, rel.confidence=$c",
                    group_id=r.group_id,
                    doc_id=r.doc_id,
                    s=r.subject,
                    o=r.object,
                    rid=r.relation_id,
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


    def delete_document_graph(self, *, group_id: str, doc_id: str) -> None:
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(doc_id).strip():
            return

        driver = self._client.get_driver()
        db = self._get_database()

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

        if db:
            with driver.session(database=db) as session:
                session.execute_write(_run)
        else:
            with driver.session() as session:
                session.execute_write(_run)


    def delete_group_graph(self, *, group_id: str) -> None:
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        driver = self._client.get_driver()
        db = self._get_database()

        def _run(tx):
            tx.run(
                "MATCH (e:Entity {group_id: $group_id}) DETACH DELETE e",
                group_id=group_id,
            )
            tx.run(
                "MATCH (d:Document {group_id: $group_id}) DETACH DELETE d",
                group_id=group_id,
            )

        if db:
            with driver.session(database=db) as session:
                session.execute_write(_run)
        else:
            with driver.session() as session:
                session.execute_write(_run)


    def search_entity_subgraph(
        self,
        *,
        group_id: str,
        entity_name: str,
        max_depth: int = 2,
        limit: int = 50,
        doc_id: Optional[str] = None,
    ) -> dict:
        """按实体名/别名检索，并扩展一定跳数的关系子图。

        返回：
        - nodes: Document/Entity 节点列表（仅包含常用字段）
        - edges: 关系边列表

        说明：
        - 本项目实体节点是 doc 级（包含 doc_id），因此默认会在同一个 doc 内扩展。
        - 如果你希望跨 doc 扩展，需要引入全局实体或跨文档对齐关系；当前先做最小可用。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(entity_name or "").strip():
            return {"nodes": [], "edges": []}

        driver = self._client.get_driver()
        db = self._get_database()

        depth = max(1, int(max_depth))
        lim = int(limit)

        where_doc = ""
        if doc_id:
            where_doc = "AND e.doc_id = $doc_id"

        cypher = (
            "MATCH (e:Entity {group_id: $group_id}) "
            "WHERE (e.name = $name OR $name IN e.aliases) "
            + where_doc
            + " WITH e LIMIT 20 "
            f"MATCH p=(e)-[r:REL*1..{depth}]-(x) "
            "RETURN p LIMIT $limit"
        )

        def _run(tx):
            return list(
                tx.run(
                    cypher,
                    group_id=group_id,
                    name=entity_name,
                    doc_id=doc_id,
                    limit=lim,
                )
            )

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for rec in records:
            p = rec.get("p")
            if p is None:
                continue
            for n in p.nodes:
                labels = list(n.labels)
                key = f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name', n.get('doc_id', ''))}"
                if key not in nodes:
                    nodes[key] = {
                        "labels": labels,
                        "group_id": n.get("group_id"),
                        "doc_id": n.get("doc_id"),
                        "name": n.get("name"),
                        "type": n.get("type"),
                        "description": n.get("description"),
                        "aliases": n.get("aliases"),
                        "doc_name": n.get("doc_name"),
                        "doc_time": n.get("doc_time"),
                    }
            for r in p.relationships:
                start = getattr(r, "start_node", None)
                end = getattr(r, "end_node", None)
                edges.append(
                    {
                        "type": r.get("type") or r.type,
                        "description": r.get("description"),
                        "confidence": r.get("confidence"),
                        "group_id": r.get("group_id"),
                        "doc_id": r.get("doc_id"),
                        "head_name": start.get("name") if start is not None else None,
                        "tail_name": end.get("name") if end is not None else None,
                    }
                )

        return {"nodes": list(nodes.values()), "edges": edges}


    def search_relations_by_entities(
        self,
        *,
        group_id: str,
        entity_names: Sequence[str],
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        """输入实体列表，返回与这些实体相连的关系（多实体检索）。

        说明：
        - 当前实现为 1-hop 关系（e)-[r:REL]-(x)。
        - entity_names 会同时匹配实体的 name 与 aliases。
        - 返回为 edges list[dict]，字段尽量与 search_entity_subgraph 的 edge 结构一致。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        names = [str(x or "").strip() for x in (entity_names or [])]
        names = [n for n in names if n]
        if not names:
            return []

        driver = self._client.get_driver()
        db = self._get_database()

        lim = int(limit)

        where_doc = ""
        if doc_id:
            where_doc = "AND e.doc_id = $doc_id"

        cypher = (
            "UNWIND $names AS name "
            "MATCH (e:Entity {group_id: $group_id}) "
            "WHERE (e.name = name OR name IN e.aliases) "
            + where_doc
            + " WITH DISTINCT e "
            "MATCH (e)-[r:REL]-(x) "
            "RETURN DISTINCT r LIMIT $limit"
        )

        def _run(tx):
            return list(
                tx.run(
                    cypher,
                    group_id=group_id,
                    names=names,
                    doc_id=doc_id,
                    limit=lim,
                )
            )

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)

        edges: list[dict] = []
        for rec in records:
            r = rec.get("r")
            if r is None:
                continue
            start = getattr(r, "start_node", None)
            end = getattr(r, "end_node", None)
            edges.append(
                {
                    "type": r.get("type") or r.type,
                    "description": r.get("description"),
                    "confidence": r.get("confidence"),
                    "group_id": r.get("group_id"),
                    "doc_id": r.get("doc_id"),
                    "relation_id": r.get("relation_id"),
                    "head_name": start.get("name") if start is not None else None,
                    "tail_name": end.get("name") if end is not None else None,
                }
            )

        return edges


    def search_group_graph(
        self,
        *,
        group_id: str,
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> dict:
        """按 group 读取图谱（nodes/edges），用于 API 展示。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        driver = self._client.get_driver()
        db = self._get_database()

        lim = int(limit)

        where_doc_e = ""
        where_doc_r = ""
        if doc_id:
            where_doc_e = "AND a.doc_id = $doc_id AND b.doc_id = $doc_id"
            where_doc_r = "AND r.doc_id = $doc_id"

        cypher = (
            "MATCH (a:Entity {group_id: $group_id})-[r:REL {group_id: $group_id}]-(b:Entity {group_id: $group_id}) "
            + where_doc_r
            + " WITH a, r, b LIMIT $limit "
            "RETURN a AS a, r AS r, b AS b"
        )

        def _run(tx):
            return list(
                tx.run(
                    cypher,
                    group_id=group_id,
                    doc_id=doc_id,
                    limit=lim,
                )
            )

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def _add_node(n):
            if n is None:
                return
            labels = list(n.labels)
            key = f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name', '')}"
            if key in nodes:
                return
            nodes[key] = {
                "labels": labels,
                "group_id": n.get("group_id"),
                "doc_id": n.get("doc_id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "description": n.get("description"),
                "aliases": n.get("aliases"),
                "doc_name": n.get("doc_name"),
                "doc_time": n.get("doc_time"),
            }

        for rec in records:
            a = rec.get("a")
            b = rec.get("b")
            r = rec.get("r")
            _add_node(a)
            _add_node(b)
            if r is None:
                continue
            start = getattr(r, "start_node", None)
            end = getattr(r, "end_node", None)
            edges.append(
                {
                    "type": r.get("type") or r.type,
                    "description": r.get("description"),
                    "confidence": r.get("confidence"),
                    "group_id": r.get("group_id"),
                    "doc_id": r.get("doc_id"),
                    "relation_id": r.get("relation_id"),
                    "head_name": start.get("name") if start is not None else None,
                    "tail_name": end.get("name") if end is not None else None,
                }
            )

        return {"nodes": list(nodes.values()), "edges": edges}


    def search_entities_by_relations(
        self,
        *,
        group_id: str,
        relation_ids: Sequence[str],
        relation_triples: Sequence[dict],
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        """输入关系列表，返回与这些关系相连的实体（多关系检索）。

        匹配策略：
        - 优先按 relation_id 精确匹配（如果提供 relation_ids）。
        - 若缺少 relation_id，可提供 relation_triples（dict 列表），按 head_name/tail_name/relation_type 匹配。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")

        rids = [str(x or "").strip() for x in (relation_ids or [])]
        rids = [x for x in rids if x]

        triples: list[dict] = []
        for t in relation_triples or []:
            if not isinstance(t, dict):
                continue
            head = str(t.get("head_name") or "").strip()
            tail = str(t.get("tail_name") or "").strip()
            rel_type = str(t.get("relation_type") or t.get("type") or "").strip()
            if not head or not tail:
                continue
            triples.append({"head": head, "tail": tail, "rel_type": rel_type})

        if not rids and not triples:
            return []

        driver = self._client.get_driver()
        db = self._get_database()

        lim = int(limit)

        where_doc = ""
        if doc_id:
            where_doc = "AND r.doc_id = $doc_id"

        cypher_by_id = (
            "UNWIND $relation_ids AS rid "
            "MATCH (a:Entity {group_id: $group_id})-[r:REL {group_id: $group_id, relation_id: rid}]-(b:Entity {group_id: $group_id}) "
            + where_doc
            + " RETURN DISTINCT a AS n UNION "
            "UNWIND $relation_ids AS rid "
            "MATCH (a:Entity {group_id: $group_id})-[r:REL {group_id: $group_id, relation_id: rid}]-(b:Entity {group_id: $group_id}) "
            + where_doc
            + " RETURN DISTINCT b AS n LIMIT $limit"
        )

        cypher_by_triple = (
            "UNWIND $triples AS t "
            "MATCH (h:Entity {group_id: $group_id}) "
            "WHERE h.name = t.head OR t.head IN h.aliases "
            "MATCH (t2:Entity {group_id: $group_id}) "
            "WHERE t2.name = t.tail OR t.tail IN t2.aliases "
            "MATCH (h)-[r:REL {group_id: $group_id}]-(t2) "
            "WHERE (t.rel_type = '' OR r.type = t.rel_type) "
            + where_doc
            + " RETURN DISTINCT h AS n UNION "
            "UNWIND $triples AS t "
            "MATCH (h:Entity {group_id: $group_id}) "
            "WHERE h.name = t.head OR t.head IN h.aliases "
            "MATCH (t2:Entity {group_id: $group_id}) "
            "WHERE t2.name = t.tail OR t.tail IN t2.aliases "
            "MATCH (h)-[r:REL {group_id: $group_id}]-(t2) "
            "WHERE (t.rel_type = '' OR r.type = t.rel_type) "
            + where_doc
            + " RETURN DISTINCT t2 AS n LIMIT $limit"
        )

        def _run(tx):
            if rids:
                return list(
                    tx.run(
                        cypher_by_id,
                        group_id=group_id,
                        relation_ids=rids,
                        doc_id=doc_id,
                        limit=lim,
                    )
                )
            return list(
                tx.run(
                    cypher_by_triple,
                    group_id=group_id,
                    triples=triples,
                    doc_id=doc_id,
                    limit=lim,
                )
            )

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)

        nodes: dict[str, dict] = {}
        for rec in records:
            n = rec.get("n")
            if n is None:
                continue
            labels = list(n.labels)
            key = f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name', '')}"
            if key in nodes:
                continue
            nodes[key] = {
                "labels": labels,
                "group_id": n.get("group_id"),
                "doc_id": n.get("doc_id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "description": n.get("description"),
                "aliases": n.get("aliases"),
                "doc_name": n.get("doc_name"),
                "doc_time": n.get("doc_time"),
            }

        return list(nodes.values())
