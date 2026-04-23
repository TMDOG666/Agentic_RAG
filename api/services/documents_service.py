from __future__ import annotations

from typing import Any

from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.graph_construction.graph_builder import GraphBuilder
from grag.model.embedding_client import EmbeddingClient
from grag.storage.repositories.milvus_graph_index_repository import MilvusGraphIndexRepository
from grag.storage.repositories.milvus_repository import MilvusVectorRepository
from grag.storage.repositories.neo4j_repository import Neo4jGraphRepository
from grag.storage.repositories.postgres_repository import PostgresGraphRepository
from grag.storage.storage_impl import DataClientGraphStorage
from grag.storage.types import DocumentRecord, GraphChunkDetailRecord, GraphIndexRecord


class DocumentsService:
    """文档资产服务。

    这一层专注于文档相关的数据访问与轻量编排：
    - 文档/文本块读取
    - 图谱进度与 checkpoint 聚合
    - 文档状态更新
    - 单块重试后的下游续跑
    """

    def __init__(self) -> None:
        data_manager = get_data_manager()
        settings = get_config_manager().get_settings()
        self._pg = PostgresGraphRepository(data_manager.get_postgres_client())
        self._neo4j = Neo4jGraphRepository(data_manager.get_neo4j_client())
        self._milvus = MilvusVectorRepository(data_manager.get_milvus_client())
        self._graph_index = MilvusGraphIndexRepository(
            data_manager.get_milvus_client(),
            collection_name=settings.get_default_graph_index_collection_name(),
            upsert_strategy="delete_then_insert",
        )
        self._embedding = EmbeddingClient(provider_name=None)

    def list_documents(self, *, group_id: str, limit: int = 200) -> list[DocumentRecord]:
        return list(self._pg.list_group_documents(group_id=group_id, limit=int(limit)) or [])

    def get_document(self, *, group_id: str, doc_id: str) -> DocumentRecord | None:
        return self._pg.get_document(group_id=group_id, doc_id=doc_id)

    def get_document_text(self, *, group_id: str, doc_id: str) -> str:
        chunks = self.list_doc_chunks(group_id=group_id, doc_id=doc_id)
        if not chunks:
            return ""
        return "\n\n".join(chunk.text for chunk in chunks if str(chunk.text or "").strip())

    def list_doc_chunks(self, *, group_id: str, doc_id: str):
        return list(self._pg.list_doc_chunks(group_id=group_id, doc_id=doc_id) or [])

    def list_doc_chunks_with_progress(self, *, group_id: str, doc_id: str) -> list[GraphChunkDetailRecord]:
        chunks = self.list_doc_chunks(group_id=group_id, doc_id=doc_id)
        checkpoint_map = self._get_chunk_checkpoint_map(group_id=group_id, doc_id=doc_id)
        return [
            self._build_chunk_detail(chunk=chunk, checkpoint=checkpoint_map.get(chunk.chunk_id))
            for chunk in chunks
        ]

    def get_doc_chunk_detail(self, *, group_id: str, doc_id: str, chunk_id: str) -> GraphChunkDetailRecord | None:
        for item in self.list_doc_chunks_with_progress(group_id=group_id, doc_id=doc_id):
            if item.chunk.chunk_id == chunk_id:
                return item
        return None

    def get_document_graph_progress(self, *, group_id: str, doc_id: str) -> dict:
        chunk_rows = list(self._pg.list_graph_chunk_checkpoints(group_id=group_id, doc_id=doc_id) or [])
        pipeline_rows = list(self._pg.list_graph_pipeline_checkpoints(group_id=group_id, doc_id=doc_id) or [])
        total_chunks = len(self.list_doc_chunks(group_id=group_id, doc_id=doc_id))
        pipeline = self._build_pipeline_progress(pipeline_rows)
        latest_stage, latest_status, latest_updated_at = self._get_latest_pipeline_status(pipeline_rows)
        completed_chunks = sum(1 for row in chunk_rows if row.status == "completed")
        failed_chunks = sum(1 for row in chunk_rows if row.status == "failed")
        processing_chunks = sum(1 for row in chunk_rows if row.status == "processing")
        return {
            "total_chunks": total_chunks,
            "completed_chunks": completed_chunks,
            "failed_chunks": failed_chunks,
            "processing_chunks": processing_chunks,
            "pending_chunks": max(total_chunks - completed_chunks - failed_chunks - processing_chunks, 0),
            "latest_stage": latest_stage,
            "latest_status": latest_status,
            "latest_updated_at": latest_updated_at,
            "pipeline": pipeline,
            "entity_alignment_fallback_count": int(
                ((pipeline.get("entity_alignment") or {}).get("payload") or {}).get("llm_compare_failed_count") or 0
            ),
        }

    def update_document_stage(
        self,
        *,
        group_id: str,
        doc_id: str,
        ingest_stage: str,
        extra_metadata: dict | None = None,
    ) -> DocumentRecord | None:
        document = self.get_document(group_id=group_id, doc_id=doc_id)
        if document is None:
            return None
        metadata = dict(document.metadata or {})
        metadata["ingest_stage"] = str(ingest_stage)
        if extra_metadata:
            metadata.update(extra_metadata)
        updated = DocumentRecord(
            group_id=document.group_id,
            doc_id=document.doc_id,
            doc_name=document.doc_name,
            doc_time=document.doc_time,
            metadata=metadata,
        )
        self._pg.upsert_document_and_chunks(document=updated, chunks=[], entities=[], relations=[])
        return updated

    def delete_document(self, *, group_id: str, doc_id: str) -> None:
        chunk_ids = self._pg.list_doc_chunk_ids(group_id=group_id, doc_id=doc_id)
        self._delete_doc_vector_assets(group_id=group_id, doc_id=doc_id, chunk_ids=chunk_ids)
        self._pg.delete_document_assets(group_id=group_id, doc_id=doc_id)
        self._rebuild_global_graph_index(group_id=group_id)

    def clear_document_graph_assets(self, *, group_id: str, doc_id: str) -> None:
        self._delete_doc_graph_assets(group_id=group_id, doc_id=doc_id)
        self._pg.delete_document_graph_assets(group_id=group_id, doc_id=doc_id)
        self._rebuild_global_graph_index(group_id=group_id)

    def retry_document_chunk(self, *, group_id: str, doc_id: str, chunk_id: str) -> dict[str, Any]:
        if not get_config_manager().reload_config():
            raise RuntimeError("重新加载 grag_config.yaml 失败")

        document = self.get_document(group_id=group_id, doc_id=doc_id)
        if document is None:
            raise ValueError(f"文档不存在: group_id={group_id}, doc_id={doc_id}")

        builder = GraphBuilder(storage=DataClientGraphStorage(milvus_upsert_strategy="delete_then_insert"))
        parsed_chunk = builder.retry_single_chunk(
            group_id=group_id,
            doc_id=doc_id,
            chunk_id=chunk_id,
            doc_name=document.doc_name,
            doc_time=document.doc_time,
        )
        chunk_detail = self.get_doc_chunk_detail(group_id=group_id, doc_id=doc_id, chunk_id=chunk_id)
        if chunk_detail is None:
            raise RuntimeError(f"chunk checkpoint not found after retry: {chunk_id}")

        progress = self.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
        graph_rebuild_task = None

        if self._all_chunks_completed(progress):
            graph_rebuild_task = self._submit_graph_rebuild(
                group_id=group_id,
                doc_id=doc_id,
                doc_name=document.doc_name,
                doc_time=document.doc_time,
            )
            progress = self.get_document_graph_progress(group_id=group_id, doc_id=doc_id)
        else:
            ingest_stage = "graph_failed" if str(parsed_chunk.error or "").strip() else "base_completed"
            self.update_document_stage(
                group_id=group_id,
                doc_id=doc_id,
                ingest_stage=ingest_stage,
                extra_metadata={
                    "graph_retry_target_chunk": chunk_id,
                    "graph_retry_chunk_status": chunk_detail.status,
                },
            )

        return {
            "chunk": chunk_detail,
            "graph_progress": progress,
            "graph_rebuild_task": graph_rebuild_task,
        }

    def _get_chunk_checkpoint_map(self, *, group_id: str, doc_id: str) -> dict[str, Any]:
        checkpoints = list(self._pg.list_graph_chunk_checkpoints(group_id=group_id, doc_id=doc_id) or [])
        return {row.chunk_id: row for row in checkpoints}

    @staticmethod
    def _build_chunk_detail(*, chunk, checkpoint) -> GraphChunkDetailRecord:
        parsed_json = dict((checkpoint.parsed_json if checkpoint else {}) or {})
        return GraphChunkDetailRecord(
            chunk=chunk,
            status=checkpoint.status if checkpoint else "pending",
            error=checkpoint.error if checkpoint else "",
            updated_at=checkpoint.updated_at if checkpoint else "",
            resolved_text=checkpoint.resolved_text if checkpoint else "",
            entity_relation_raw=checkpoint.entity_relation_raw if checkpoint else "",
            parsed_json=parsed_json,
        )

    @staticmethod
    def _build_pipeline_progress(pipeline_rows) -> dict[str, dict[str, Any]]:
        return {
            row.stage: {
                "status": row.status,
                "error": row.error,
                "updated_at": row.updated_at,
                "payload": dict(row.payload_json or {}),
            }
            for row in pipeline_rows
        }

    @staticmethod
    def _get_latest_pipeline_status(pipeline_rows) -> tuple[str, str, str]:
        latest_stage = ""
        latest_status = ""
        latest_updated_at = ""
        for row in pipeline_rows:
            if row.updated_at >= latest_updated_at:
                latest_stage = row.stage
                latest_status = row.status
                latest_updated_at = row.updated_at
        return latest_stage, latest_status, latest_updated_at

    @staticmethod
    def _all_chunks_completed(progress: dict[str, Any]) -> bool:
        total_chunks = int(progress.get("total_chunks") or 0)
        return (
            total_chunks > 0
            and int(progress.get("completed_chunks") or 0) == total_chunks
            and int(progress.get("failed_chunks") or 0) == 0
            and int(progress.get("processing_chunks") or 0) == 0
        )

    def _submit_graph_rebuild(
        self,
        *,
        group_id: str,
        doc_id: str,
        doc_name: str,
        doc_time: str,
    ) -> dict[str, Any]:
        from grag.graph_construction.async_graph_service import AsyncGraphBuildService

        self.update_document_stage(
            group_id=group_id,
            doc_id=doc_id,
            ingest_stage="graph_retrying",
            extra_metadata={"graph_rebuild_trigger": "chunk_retry"},
        )
        task = AsyncGraphBuildService.instance().submit(
            text=self.get_document_text(group_id=group_id, doc_id=doc_id),
            group_id=group_id,
            doc_id=doc_id,
            doc_name=doc_name,
            doc_time=doc_time,
        )
        return {"task_id": task.task_id, "status": task.status, "stage": task.stage}

    def _delete_doc_vector_assets(self, *, group_id: str, doc_id: str, chunk_ids: list[str]) -> None:
        try:
            self._milvus.delete_chunks_by_ids(group_id=group_id, chunk_ids=chunk_ids)
        except Exception:
            pass
        self._delete_doc_graph_assets(group_id=group_id, doc_id=doc_id)

    def _delete_doc_graph_assets(self, *, group_id: str, doc_id: str) -> None:
        try:
            self._graph_index.delete_by_doc_id(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass
        try:
            self._neo4j.delete_document_graph(group_id=group_id, doc_id=doc_id)
        except Exception:
            pass

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
        metadata: list[tuple[str, object]] = []
        for entity in global_entities:
            aliases = " ".join([alias for alias in entity.aliases if str(alias).strip()])
            texts.append(f"{entity.canonical_name}\n{aliases}\n{entity.description}".strip())
            metadata.append(("entity", entity))
        for relation in global_relations:
            texts.append(f"{relation.subject_name} -[{relation.relation_type}]-> {relation.object_name}\n{relation.description}".strip())
            metadata.append(("relation", relation))

        vectors = self._embedding.embed_texts(texts) if texts else []
        records: list[GraphIndexRecord] = []
        for (kind, obj), vector, text in zip(metadata, vectors, texts):
            if kind == "entity":
                entity = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"e:{entity.group_id}:__global__:{entity.global_entity_id}",
                        kind="entity",
                        group_id=entity.group_id,
                        doc_id="__global__",
                        source_id=entity.global_entity_id,
                        name=entity.canonical_name,
                        text=text,
                        embedding=list(vector),
                    )
                )
            else:
                relation = obj  # type: ignore[assignment]
                records.append(
                    GraphIndexRecord(
                        pk=f"r:{relation.group_id}:__global__:{relation.global_relation_id}",
                        kind="relation",
                        group_id=relation.group_id,
                        doc_id="__global__",
                        source_id=relation.global_relation_id,
                        name=relation.relation_type,
                        text=text,
                        embedding=list(vector),
                        head_name=relation.subject_name,
                        tail_name=relation.object_name,
                        relation_type=relation.relation_type,
                    )
                )

        if records:
            self._graph_index.upsert_records(records=records)
