from __future__ import annotations

from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.model.embedding_client import EmbeddingClient
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository
from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.types import DocumentRecord, GraphIndexRecord


class DocumentsService:
    def __init__(self) -> None:
        dm = get_data_manager()
        settings = get_config_manager().get_settings()
        self._pg = PostgresGraphRepository(dm.get_postgres_client())
        self._neo4j = Neo4jGraphRepository(dm.get_neo4j_client())
        self._milvus = MilvusVectorRepository(dm.get_milvus_client())
        self._graph_index = MilvusGraphIndexRepository(
            dm.get_milvus_client(),
            collection_name=settings.get_default_graph_index_collection_name(),
            upsert_strategy="delete_then_insert",
        )
        self._embedding = EmbeddingClient(provider_name=None)

    def list_documents(self, *, group_id: str, limit: int = 200) -> list[DocumentRecord]:
        return list(self._pg.list_group_documents(group_id=group_id, limit=int(limit)) or [])

    def get_document(self, *, group_id: str, doc_id: str) -> DocumentRecord | None:
        return self._pg.get_document(group_id=group_id, doc_id=doc_id)

    def delete_document(self, *, group_id: str, doc_id: str) -> None:
        chunk_ids = self._pg.list_doc_chunk_ids(group_id=group_id, doc_id=doc_id)
        try:
            self._milvus.delete_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        except Exception:
            pass

        try:
            self._graph_index.delete_by_doc_id(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass

        try:
            self._neo4j.delete_document_graph(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass

        self._pg.delete_document_assets(group_id=group_id, doc_id=doc_id)
        self._rebuild_global_graph_index(group_id=group_id)

    def _rebuild_global_graph_index(self, *, group_id: str) -> None:
        try:
            self._graph_index.delete_by_doc_id(group_id=group_id, doc_id="__global__")
        except Exception:
            pass

        global_entities = list(self._pg.list_group_global_entities(group_id=group_id, limit=5000) or [])
        global_relations = list(self._pg.list_group_global_relations(group_id=group_id, limit=5000) or [])
        if not global_entities and not global_relations:
            return

        texts: list[str] = []
        meta: list[tuple[str, object]] = []
        for e in global_entities:
            aliases = " ".join([a for a in e.aliases if str(a).strip()])
            texts.append(f"{e.canonical_name}\n{aliases}\n{e.description}".strip())
            meta.append(("entity", e))
        for r in global_relations:
            texts.append(f"{r.subject_name} -[{r.relation_type}]-> {r.object_name}\n{r.description}".strip())
            meta.append(("relation", r))

        vecs = self._embedding.embed_texts(texts) if texts else []
        records: list[GraphIndexRecord] = []
        for (kind, obj), vec, text in zip(meta, vecs, texts):
            if kind == "entity":
                e = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"e:{e.group_id}:__global__:{e.global_entity_id}",
                        kind="entity",
                        group_id=e.group_id,
                        doc_id="__global__",
                        source_id=e.global_entity_id,
                        name=e.canonical_name,
                        text=text,
                        embedding=list(vec),
                    )
                )
            else:
                r = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"r:{r.group_id}:__global__:{r.global_relation_id}",
                        kind="relation",
                        group_id=r.group_id,
                        doc_id="__global__",
                        source_id=r.global_relation_id,
                        name=r.relation_type,
                        text=text,
                        embedding=list(vec),
                        head_name=r.subject_name,
                        tail_name=r.object_name,
                        relation_type=r.relation_type,
                    )
                )

        if records:
            self._graph_index.upsert_records(records=records)
