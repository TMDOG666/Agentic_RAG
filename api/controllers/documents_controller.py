from __future__ import annotations

from fastapi import APIRouter

from api.presentation.trace_dto import build_graph_trace_timeline, map_chunk_checkpoint_to_step
from api.schemas.chunks import ChunkOut
from api.schemas.documents import DocumentOut
from api.schemas.ingest_tasks import IngestTaskOut
from api.services.documents_service import DocumentsService

router = APIRouter()


def _build_chunk_out(item) -> ChunkOut:
    chunk_out = ChunkOut.from_chunk_record(
        item.chunk,
        status=item.status,
        error=item.error,
        updated_at=item.updated_at,
        resolved_text=item.resolved_text,
        entity_relation_raw=item.entity_relation_raw,
        parsed_entities=list((item.parsed_json or {}).get("entities") or []),
        parsed_relations=list((item.parsed_json or {}).get("relations") or []),
        parse_errors=list((item.parsed_json or {}).get("errors") or []),
        task_id=str(item.latest_task_id or ""),
        task_status=str(item.latest_task_status or ""),
        task_kind=str(item.latest_task_kind or ""),
        task_updated_at=str(item.latest_task_updated_at or ""),
        task_message=str(item.latest_task_message or ""),
    )
    chunk_out.trace_step = map_chunk_checkpoint_to_step(chunk_out)
    return chunk_out


@router.get("")
def list_documents(group_id: str, limit: int = 200) -> list[DocumentOut]:
    svc = DocumentsService()
    docs = svc.list_documents(group_id=group_id, limit=limit)
    out: list[DocumentOut] = []
    for d in docs:
        graph_progress = svc.get_document_graph_progress(group_id=group_id, doc_id=d.doc_id)
        out.append(
            DocumentOut.from_document_record(
                d,
                graph_progress=graph_progress,
                graph_trace=build_graph_trace_timeline(graph_progress),
            )
        )
    return out


@router.get("/{doc_id}")
def get_document(group_id: str, doc_id: str) -> DocumentOut | None:
    svc = DocumentsService()
    d = svc.get_document(group_id=group_id, doc_id=doc_id)
    if d is None:
        return None
    graph_progress = svc.get_document_graph_progress(group_id=group_id, doc_id=d.doc_id)
    return DocumentOut.from_document_record(
        d,
        graph_progress=graph_progress,
        graph_trace=build_graph_trace_timeline(graph_progress),
    )


@router.get("/{doc_id}/chunks")
def list_document_chunks(group_id: str, doc_id: str, limit: int = 5000) -> list[ChunkOut]:
    svc = DocumentsService()
    chunks = svc.list_doc_chunks_with_progress(group_id=group_id, doc_id=doc_id)
    return [_build_chunk_out(item) for item in chunks[: int(limit)]]


@router.post("/{doc_id}/chunks/{chunk_id}/retry")
def retry_document_chunk(group_id: str, doc_id: str, chunk_id: str) -> dict:
    svc = DocumentsService()
    result = svc.retry_document_chunk(group_id=group_id, doc_id=doc_id, chunk_id=chunk_id)
    chunk = result.get("chunk")
    task = result.get("task")
    if chunk is None:
        raise ValueError(f"chunk not found after retry submit: {chunk_id}")
    if task is None:
        raise ValueError(f"chunk retry task not found after submit: {chunk_id}")
    return {
        "task": IngestTaskOut.from_record(task).model_dump(),
        "chunk": _build_chunk_out(chunk).model_dump(),
        "graph_progress": result.get("graph_progress") or {},
        "graph_trace": build_graph_trace_timeline(result.get("graph_progress") or {}).model_dump(),
    }


@router.delete("/{doc_id}")
def delete_document(group_id: str, doc_id: str) -> dict:
    svc = DocumentsService()
    svc.delete_document(group_id=group_id, doc_id=doc_id)
    return {"deleted": True}
