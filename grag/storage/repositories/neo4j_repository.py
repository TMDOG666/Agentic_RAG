from __future__ import annotations

from typing import Optional, Sequence

from grag.data_client.neo4j_client import Neo4jClient

from ..types import DocumentRecord, GlobalEntityRecord, GlobalRelationRecord, GraphEntityRecord, GraphRelationRecord


class Neo4jGraphRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client
        self._constraints_initialized = False

    def _get_database(self):
        try:
            return self._client._get_config().database
        except Exception:
            return None

    def ensure_constraints(self) -> None:
        if self._constraints_initialized:
            return
        driver = self._client.get_driver()
        db = self._get_database()

        def _run(session):
            statements = [
                "CREATE CONSTRAINT grag_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.group_id, e.doc_id, e.name) IS UNIQUE",
                "CREATE CONSTRAINT grag_global_entity_key IF NOT EXISTS FOR (e:GlobalEntity) REQUIRE (e.group_id, e.name) IS UNIQUE",
            ]
            for stmt in statements:
                try:
                    session.run(stmt)
                except Exception:
                    pass

        if db:
            with driver.session(database=db) as session:
                _run(session)
        else:
            with driver.session() as session:
                _run(session)
        self._constraints_initialized = True

    def upsert_graph(
        self,
        *,
        document: DocumentRecord,
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
        global_entities: Sequence[GlobalEntityRecord] = (),
        global_relations: Sequence[GlobalRelationRecord] = (),
    ) -> None:
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

            for e in global_entities:
                tx.run(
                    "MERGE (n:GlobalEntity {group_id: $group_id, name: $name}) "
                    "SET n.global_entity_id=$global_entity_id, n.type=$type, n.description=$description, n.aliases=$aliases",
                    group_id=e.group_id,
                    name=e.canonical_name,
                    global_entity_id=e.global_entity_id,
                    type=e.type,
                    description=e.description,
                    aliases=list(e.aliases),
                )

            for r in global_relations:
                tx.run(
                    "MATCH (s:GlobalEntity {group_id: $group_id, name: $s}) "
                    "MATCH (o:GlobalEntity {group_id: $group_id, name: $o}) "
                    "MERGE (s)-[rel:GREL {group_id: $group_id, global_relation_id: $rid}]->(o) "
                    "SET rel.type=$t, rel.description=$d, rel.confidence=$c",
                    group_id=r.group_id,
                    s=r.subject_name,
                    o=r.object_name,
                    rid=r.global_relation_id,
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
        if not str(group_id).strip() or not str(doc_id).strip():
            return
        driver = self._client.get_driver()
        db = self._get_database()

        def _run(tx):
            tx.run("MATCH (e:Entity {group_id: $group_id, doc_id: $doc_id}) DETACH DELETE e", group_id=group_id, doc_id=doc_id)
            tx.run("MATCH (d:Document {group_id: $group_id, doc_id: $doc_id}) DETACH DELETE d", group_id=group_id, doc_id=doc_id)

        if db:
            with driver.session(database=db) as session:
                session.execute_write(_run)
        else:
            with driver.session() as session:
                session.execute_write(_run)

    def delete_group_graph(self, *, group_id: str) -> None:
        if not str(group_id).strip():
            return
        driver = self._client.get_driver()
        db = self._get_database()

        def _run(tx):
            tx.run("MATCH (e:Entity {group_id: $group_id}) DETACH DELETE e", group_id=group_id)
            tx.run("MATCH (d:Document {group_id: $group_id}) DETACH DELETE d", group_id=group_id)
            tx.run("MATCH (e:GlobalEntity {group_id: $group_id}) DETACH DELETE e", group_id=group_id)

        if db:
            with driver.session(database=db) as session:
                session.execute_write(_run)
        else:
            with driver.session() as session:
                session.execute_write(_run)

    def _search_entity_subgraph_doc(self, *, group_id: str, entity_name: str, max_depth: int, limit: int, doc_id: Optional[str]) -> dict:
        driver = self._client.get_driver()
        db = self._get_database()
        where_doc = "AND e.doc_id = $doc_id" if doc_id else ""
        cypher = (
            "MATCH (e:Entity {group_id: $group_id}) "
            "WHERE (e.name = $name OR $name IN e.aliases) "
            + where_doc
            + f" WITH e LIMIT 20 MATCH p=(e)-[r:REL*1..{max(1, int(max_depth))}]-(x) RETURN p LIMIT $limit"
        )

        def _run(tx):
            return list(tx.run(cypher, group_id=group_id, name=entity_name, doc_id=doc_id, limit=int(limit)))

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)
        return self._paths_to_subgraph(records)

    def _search_entity_subgraph_global(self, *, group_id: str, entity_name: str, max_depth: int, limit: int) -> dict:
        driver = self._client.get_driver()
        db = self._get_database()
        cypher = (
            "MATCH (e:GlobalEntity {group_id: $group_id}) "
            "WHERE (e.name = $name OR $name IN e.aliases) "
            + f"WITH e LIMIT 20 MATCH p=(e)-[r:GREL*1..{max(1, int(max_depth))}]-(x) RETURN p LIMIT $limit"
        )

        def _run(tx):
            return list(tx.run(cypher, group_id=group_id, name=entity_name, limit=int(limit)))

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)
        return self._paths_to_subgraph(records)

    def search_entity_subgraph(
        self,
        *,
        group_id: str,
        entity_name: str,
        max_depth: int = 2,
        limit: int = 50,
        doc_id: Optional[str] = None,
    ) -> dict:
        if not str(group_id).strip() or not str(entity_name or "").strip():
            return {"nodes": [], "edges": []}
        if doc_id:
            return self._search_entity_subgraph_doc(group_id=group_id, entity_name=entity_name, max_depth=max_depth, limit=limit, doc_id=doc_id)
        return self._search_entity_subgraph_global(group_id=group_id, entity_name=entity_name, max_depth=max_depth, limit=limit)

    def search_relations_by_entities(
        self,
        *,
        group_id: str,
        entity_names: Sequence[str],
        limit: int = 200,
        doc_id: Optional[str] = None,
    ) -> list[dict]:
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        names = [str(x or "").strip() for x in entity_names or [] if str(x or "").strip()]
        if not names:
            return []
        driver = self._client.get_driver()
        db = self._get_database()

        if doc_id:
            cypher = (
                "UNWIND $names AS name "
                "MATCH (e:Entity {group_id: $group_id, doc_id: $doc_id}) "
                "WHERE (e.name = name OR name IN e.aliases) "
                "WITH DISTINCT e MATCH (e)-[r:REL]-(x) RETURN DISTINCT r LIMIT $limit"
            )
            params = {"group_id": group_id, "doc_id": doc_id, "names": names, "limit": int(limit)}
        else:
            cypher = (
                "UNWIND $names AS name "
                "MATCH (e:GlobalEntity {group_id: $group_id}) "
                "WHERE (e.name = name OR name IN e.aliases) "
                "WITH DISTINCT e MATCH (e)-[r:GREL]-(x) RETURN DISTINCT r LIMIT $limit"
            )
            params = {"group_id": group_id, "names": names, "limit": int(limit)}

        def _run(tx):
            return list(tx.run(cypher, **params))

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)
        return self._records_to_edges(records)

    def search_group_graph(self, *, group_id: str, limit: int = 200, doc_id: Optional[str] = None) -> dict:
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        driver = self._client.get_driver()
        db = self._get_database()
        if doc_id:
            cypher = (
                "MATCH (a:Entity {group_id: $group_id, doc_id: $doc_id})-[r:REL {group_id: $group_id, doc_id: $doc_id}]-(b:Entity {group_id: $group_id, doc_id: $doc_id}) "
                "WITH a, r, b LIMIT $limit RETURN a AS a, r AS r, b AS b"
            )
            params = {"group_id": group_id, "doc_id": doc_id, "limit": int(limit)}
        else:
            cypher = (
                "MATCH (a:GlobalEntity {group_id: $group_id})-[r:GREL {group_id: $group_id}]-(b:GlobalEntity {group_id: $group_id}) "
                "WITH a, r, b LIMIT $limit RETURN a AS a, r AS r, b AS b"
            )
            params = {"group_id": group_id, "limit": int(limit)}

        def _run(tx):
            return list(tx.run(cypher, **params))

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)

        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        for rec in records:
            for key in ("a", "b"):
                n = rec.get(key)
                if n is None:
                    continue
                labels = list(n.labels)
                node_key = f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name', '')}"
                nodes.setdefault(
                    node_key,
                    {
                        "labels": labels,
                        "group_id": n.get("group_id"),
                        "doc_id": n.get("doc_id"),
                        "name": n.get("name"),
                        "type": n.get("type"),
                        "description": n.get("description"),
                        "aliases": n.get("aliases"),
                    },
                )
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
                    "relation_id": r.get("relation_id") or r.get("global_relation_id"),
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
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        rids = [str(x or "").strip() for x in relation_ids or [] if str(x or "").strip()]
        triples = []
        for t in relation_triples or []:
            if not isinstance(t, dict):
                continue
            head = str(t.get("head_name") or "").strip()
            tail = str(t.get("tail_name") or "").strip()
            rel_type = str(t.get("relation_type") or t.get("type") or "").strip()
            if head and tail:
                triples.append({"head": head, "tail": tail, "rel_type": rel_type})
        if not rids and not triples:
            return []
        driver = self._client.get_driver()
        db = self._get_database()

        if doc_id:
            rid_key = "relation_id"
            label = "Entity"
            rel_label = "REL"
            node_doc_filter = "{group_id: $group_id, doc_id: $doc_id}"
            rel_doc_filter = "{group_id: $group_id, doc_id: $doc_id"
            extra_params = {"doc_id": doc_id}
        else:
            rid_key = "global_relation_id"
            label = "GlobalEntity"
            rel_label = "GREL"
            node_doc_filter = "{group_id: $group_id}"
            rel_doc_filter = "{group_id: $group_id"
            extra_params = {}

        if rids:
            cypher = (
                f"UNWIND $relation_ids AS rid MATCH (a:{label} {node_doc_filter})-[r:{rel_label} {{group_id: $group_id, {rid_key}: rid}}]-(b:{label} {node_doc_filter}) "
                "RETURN DISTINCT a AS n UNION "
                f"UNWIND $relation_ids AS rid MATCH (a:{label} {node_doc_filter})-[r:{rel_label} {{group_id: $group_id, {rid_key}: rid}}]-(b:{label} {node_doc_filter}) "
                "RETURN DISTINCT b AS n LIMIT $limit"
            )
            params = {"group_id": group_id, "relation_ids": rids, "limit": int(limit), **extra_params}
        else:
            cypher = (
                "UNWIND $triples AS t "
                f"MATCH (h:{label} {{group_id: $group_id}}) WHERE h.name = t.head OR t.head IN h.aliases "
                f"MATCH (t2:{label} {{group_id: $group_id}}) WHERE t2.name = t.tail OR t.tail IN t2.aliases "
                f"MATCH (h)-[r:{rel_label} {{group_id: $group_id}}]-(t2) "
                "WHERE (t.rel_type = '' OR r.type = t.rel_type) "
                + ("AND r.doc_id = $doc_id " if doc_id else "")
                + "RETURN DISTINCT h AS n UNION "
                "UNWIND $triples AS t "
                f"MATCH (h:{label} {{group_id: $group_id}}) WHERE h.name = t.head OR t.head IN h.aliases "
                f"MATCH (t2:{label} {{group_id: $group_id}}) WHERE t2.name = t.tail OR t.tail IN t2.aliases "
                f"MATCH (h)-[r:{rel_label} {{group_id: $group_id}}]-(t2) "
                "WHERE (t.rel_type = '' OR r.type = t.rel_type) "
                + ("AND r.doc_id = $doc_id " if doc_id else "")
                + "RETURN DISTINCT t2 AS n LIMIT $limit"
            )
            params = {"group_id": group_id, "triples": triples, "limit": int(limit), **extra_params}

        def _run(tx):
            return list(tx.run(cypher, **params))

        if db:
            with driver.session(database=db) as session:
                records = session.execute_read(_run)
        else:
            with driver.session() as session:
                records = session.execute_read(_run)
        return self._records_to_nodes(records, key_name="n")

    @staticmethod
    def _paths_to_subgraph(records: Sequence[object]) -> dict:
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
                        "relation_id": r.get("relation_id") or r.get("global_relation_id"),
                        "head_name": start.get("name") if start is not None else None,
                        "tail_name": end.get("name") if end is not None else None,
                    }
                )
        return {"nodes": list(nodes.values()), "edges": edges}

    @staticmethod
    def _records_to_edges(records: Sequence[object]) -> list[dict]:
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
                    "relation_id": r.get("relation_id") or r.get("global_relation_id"),
                    "head_name": start.get("name") if start is not None else None,
                    "tail_name": end.get("name") if end is not None else None,
                }
            )
        return edges

    @staticmethod
    def _records_to_nodes(records: Sequence[object], *, key_name: str) -> list[dict]:
        nodes: dict[str, dict] = {}
        for rec in records:
            n = rec.get(key_name)
            if n is None:
                continue
            labels = list(n.labels)
            key = f"{labels}:{n.get('group_id')}:{n.get('doc_id')}:{n.get('name', '')}"
            nodes.setdefault(
                key,
                {
                    "labels": labels,
                    "group_id": n.get("group_id"),
                    "doc_id": n.get("doc_id"),
                    "name": n.get("name"),
                    "type": n.get("type"),
                    "description": n.get("description"),
                    "aliases": n.get("aliases"),
                    "doc_name": n.get("doc_name"),
                    "doc_time": n.get("doc_time"),
                },
            )
        return list(nodes.values())
