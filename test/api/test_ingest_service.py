from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

fake_documents_service = types.ModuleType("api.services.documents_service")
fake_documents_service.DocumentsService = object
sys.modules.setdefault("api.services.documents_service", fake_documents_service)

fake_async_graph_service = types.ModuleType("grag.graph_construction.async_graph_service")
fake_async_graph_service.AsyncGraphBuildService = type("AsyncGraphBuildService", (), {"instance": staticmethod(lambda: object())})
sys.modules.setdefault("grag.graph_construction.async_graph_service", fake_async_graph_service)

fake_graph_builder_module = types.ModuleType("grag.graph_construction.graph_builder")
fake_graph_builder_module.GraphBuilder = type("GraphBuilder", (), {})
sys.modules.setdefault("grag.graph_construction.graph_builder", fake_graph_builder_module)

fake_storage_impl = types.ModuleType("grag.storage.storage_impl")
fake_storage_impl.DataClientGraphStorage = type("DataClientGraphStorage", (), {"__init__": lambda self, *args, **kwargs: None})
sys.modules.setdefault("grag.storage.storage_impl", fake_storage_impl)

fake_document_processor = types.ModuleType("grag.preprocessing.document_processor")
fake_document_processor.DocumentProcessor = type("DocumentProcessor", (), {})
sys.modules.setdefault("grag.preprocessing.document_processor", fake_document_processor)

from api.schemas.ingest import IngestTextIn
from api.services.ingest_service import IngestService


def test_ingest_text_deletes_existing_document_before_async_graph_build(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    class FakeDocumentsService:
        def get_document(self, *, group_id: str, doc_id: str):
            calls.append(("get", group_id, doc_id))
            return SimpleNamespace(doc_id=doc_id)

        def delete_document(self, *, group_id: str, doc_id: str) -> None:
            calls.append(("delete", group_id, doc_id))

    class FakeBuilder:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_base_and_save(self, **kwargs):
            calls.append(("base", kwargs["group_id"], kwargs["doc_id"]))
            return SimpleNamespace(
                document=SimpleNamespace(
                    doc_id=kwargs["doc_id"],
                    doc_name=kwargs["doc_name"],
                    doc_time=kwargs["doc_time"],
                ),
                chunks=[object()],
                embeddings=[object()],
            )

    class FakeAsyncGraph:
        def submit(self, **kwargs):
            calls.append(("submit", kwargs["group_id"], kwargs["doc_id"]))
            return SimpleNamespace(task_id="task-1", status="pending", stage="queued")

    monkeypatch.setattr("api.services.ingest_service.DocumentsService", FakeDocumentsService)
    monkeypatch.setattr("api.services.ingest_service.GraphBuilder", FakeBuilder)
    monkeypatch.setattr("api.services.ingest_service.AsyncGraphBuildService.instance", lambda: FakeAsyncGraph())

    svc = IngestService()
    out = svc.ingest_text(
        IngestTextIn(
            group_id="g1",
            doc_time="2026-04-05T00:00:00+08:00",
            doc_name="doc.txt",
            text="hello",
            doc_id="doc-1",
        )
    )

    assert out.doc_id == "doc-1"
    assert out.task_id == "task-1"
    assert calls == [
        ("get", "g1", "doc-1"),
        ("delete", "g1", "doc-1"),
        ("base", "g1", "doc-1"),
        ("submit", "g1", "doc-1"),
    ]


def test_ingest_text_skips_delete_for_blank_doc_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    class FakeDocumentsService:
        def get_document(self, *, group_id: str, doc_id: str):
            calls.append(("get", group_id, doc_id))
            return None

        def delete_document(self, *, group_id: str, doc_id: str) -> None:
            calls.append(("delete", group_id, doc_id))

    class FakeBuilder:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_base_and_save(self, **kwargs):
            calls.append(("base", kwargs["group_id"], kwargs["doc_id"]))
            return SimpleNamespace(
                document=SimpleNamespace(
                    doc_id="generated-doc",
                    doc_name=kwargs["doc_name"],
                    doc_time=kwargs["doc_time"],
                ),
                chunks=[],
                embeddings=[],
            )

    class FakeAsyncGraph:
        def submit(self, **kwargs):
            calls.append(("submit", kwargs["group_id"], kwargs["doc_id"]))
            return SimpleNamespace(task_id="task-2", status="pending", stage="queued")

    monkeypatch.setattr("api.services.ingest_service.DocumentsService", FakeDocumentsService)
    monkeypatch.setattr("api.services.ingest_service.GraphBuilder", FakeBuilder)
    monkeypatch.setattr("api.services.ingest_service.AsyncGraphBuildService.instance", lambda: FakeAsyncGraph())

    svc = IngestService()
    out = svc.ingest_text(
        IngestTextIn(
            group_id="g1",
            doc_time="2026-04-05T00:00:00+08:00",
            doc_name="doc.txt",
            text="hello",
            doc_id="   ",
        )
    )

    assert out.doc_id == "generated-doc"
    assert out.task_id == "task-2"
    assert calls == [
        ("base", "g1", None),
        ("submit", "g1", "generated-doc"),
    ]
