from __future__ import annotations

from fastapi import APIRouter

from api.schemas.chunks import ChunkOut
from api.schemas.documents import DocumentOut
from api.services.documents_service import DocumentsService

router = APIRouter()


@router.get("")
def list_documents(group_id: str, limit: int = 200) -> list[DocumentOut]:
    svc = DocumentsService()
    docs = svc.list_documents(group_id=group_id, limit=limit)
    return [
        DocumentOut.from_document_record(
            d,
            graph_progress=svc.get_document_graph_progress(group_id=group_id, doc_id=d.doc_id),
        )
        for d in docs
    ]


@router.get("/{doc_id}")
def get_document(group_id: str, doc_id: str) -> DocumentOut | None:
    svc = DocumentsService()
    d = svc.get_document(group_id=group_id, doc_id=doc_id)
    return (
        DocumentOut.from_document_record(
            d,
            graph_progress=svc.get_document_graph_progress(group_id=group_id, doc_id=d.doc_id),
        )
        if d is not None
        else None
    )


@router.get("/{doc_id}/chunks")
def list_document_chunks(group_id: str, doc_id: str, limit: int = 5000) -> list[ChunkOut]:
    svc = DocumentsService()
    chunks = svc.list_doc_chunks_with_progress(group_id=group_id, doc_id=doc_id)
    return [
        ChunkOut.from_chunk_record(
            item.chunk,
            status=item.status,
            error=item.error,
            updated_at=item.updated_at,
            resolved_text=item.resolved_text,
            entity_relation_raw=item.entity_relation_raw,
            parsed_entities=list((item.parsed_json or {}).get("entities") or []),
            parsed_relations=list((item.parsed_json or {}).get("relations") or []),
            parse_errors=list((item.parsed_json or {}).get("errors") or []),
        )
        for item in chunks[: int(limit)]
    ]


@router.post("/{doc_id}/chunks/{chunk_id}/retry")
def retry_document_chunk(group_id: str, doc_id: str, chunk_id: str) -> dict:
    svc = DocumentsService()
    result = svc.retry_document_chunk(group_id=group_id, doc_id=doc_id, chunk_id=chunk_id)
    chunk = result.get("chunk")
    if chunk is None:
        raise ValueError(f"chunk not found after retry: {chunk_id}")
    return {
        "chunk": ChunkOut.from_chunk_record(
            chunk.chunk,
            status=chunk.status,
            error=chunk.error,
            updated_at=chunk.updated_at,
            resolved_text=chunk.resolved_text,
            entity_relation_raw=chunk.entity_relation_raw,
            parsed_entities=list((chunk.parsed_json or {}).get("entities") or []),
            parsed_relations=list((chunk.parsed_json or {}).get("relations") or []),
            parse_errors=list((chunk.parsed_json or {}).get("errors") or []),
        ).model_dump(),
        "graph_progress": result.get("graph_progress") or {},
        "graph_rebuild_task": result.get("graph_rebuild_task"),
    }


@router.delete("/{doc_id}")
def delete_document(group_id: str, doc_id: str) -> dict:
    svc = DocumentsService()
    svc.delete_document(group_id=group_id, doc_id=doc_id)
    return {"deleted": True}
