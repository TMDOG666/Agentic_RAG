from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from types import SimpleNamespace

fake_entrypoint = types.ModuleType("grag.entrypoint")
fake_entrypoint.GRAG = object
sys.modules.setdefault("grag.entrypoint", fake_entrypoint)

fake_data_client = types.ModuleType("grag.data_client")
fake_data_client.DataManager = object
fake_data_client.get_data_manager = lambda: type("DM", (), {"get_postgres_client": lambda self: object()})()
sys.modules.setdefault("grag.data_client", fake_data_client)

fake_pg_repo_module = types.ModuleType("grag.storage.repositories.postgres_repository")
fake_pg_repo_module.PostgresGraphRepository = type("PostgresGraphRepository", (), {"__init__": lambda self, *args, **kwargs: None})
sys.modules.setdefault("grag.storage.repositories.postgres_repository", fake_pg_repo_module)

from api.schemas.retrieval import RetrievalRequest
from api.services.retrieval_service import RetrievalService


@dataclass(frozen=True)
class EntityMentionRecord:
    mention_id: str
    group_id: str
    doc_id: str
    chunk_id: str
    entity_name: str
    entity_type: str
    description: str
    evidence_text: str
    local_entity_id: str
    global_entity_id: str


class _FakePG:
    def list_entity_mentions(self, **kwargs):
        return []

    def list_relation_mentions(self, **kwargs):
        return []

    def get_chunks_by_ids(self, **kwargs):
        return []


class _FakeGRAG:
    def entities(self, **kwargs):
        return [
            {"doc_id": "__global__", "source_id": "ge-1", "name": "Alpha", "score": 0.9},
        ]

    def relations(self, **kwargs):
        return [
            {
                "doc_id": "__global__",
                "source_id": "gr-1",
                "relation_type": "owns",
                "head_name": "Alpha",
                "tail_name": "Beta",
                "score": 0.8,
            }
        ]

    def relations_by_entities(self, **kwargs):
        return [
            {
                "relation_id": "gr-1",
                "type": "owns",
                "relation_type": "owns",
                "head_name": "Alpha",
                "tail_name": "Beta",
            }
        ]

    def entities_by_relations(self, **kwargs):
        return [
            {"name": "Alpha"},
            {"name": "Beta"},
        ]

    def chunks_vector(self, **kwargs):
        return SimpleNamespace(
            keyword_hits=[],
            semantic_hits=[
                SimpleNamespace(
                    group_id="g1",
                    doc_id="d1",
                    doc_time="2026-01-01T00:00:00Z",
                    chunk_id="c1",
                    score=0.91,
                    text="vector hit",
                )
            ],
            graph=None,
            local_graph=None,
            global_graph=None,
        )

    def chunks_keyword(self, **kwargs):
        return SimpleNamespace(
            keyword_hits=[
                SimpleNamespace(
                    group_id="g1",
                    doc_id="d1",
                    chunk_id="c1",
                    index=0,
                    text="keyword hit",
                    score=1.23,
                )
            ],
            semantic_hits=[],
            graph=None,
            local_graph=None,
            global_graph=None,
        )


def test_graph_search_combines_entity_relation_graph_and_evidence() -> None:
    svc = RetrievalService()
    svc._grag = _FakeGRAG()
    svc._pg = _FakePG()

    resp = svc.retrieve(
        RetrievalRequest(
            group_id="g1",
            mode="graph_search",
            query="Alpha owns Beta",
            include_evidence=True,
        )
    )

    result = resp.result
    assert result["entities"][0]["name"] == "Alpha"
    assert result["relations"][0]["relation_type"] == "owns"
    assert result["graph"]["entity_names"] == ["Alpha", "Beta"]
    assert len(result["graph"]["relations"]) == 1
    assert result["meta"]["mode"] == "graph_search"
    assert "graph" in result["meta"]["source_modes"]
    assert "evidence" in result
    assert result["evidence"]["entities"]["entity_mentions"] == []
    assert result["evidence"]["relations"]["relation_mentions"] == []


def test_entity_retrieval_with_evidence_backfills_mentions_and_chunks() -> None:
    class FakePG(_FakePG):
        def list_entity_mentions(self, **kwargs):
            return [
                EntityMentionRecord(
                    mention_id="m1",
                    group_id="g1",
                    doc_id="d1",
                    chunk_id="c1",
                    entity_name="Alpha",
                    entity_type="Org",
                    description="desc",
                    evidence_text="evidence",
                    local_entity_id="le1",
                    global_entity_id="ge1",
                )
            ]

        def get_chunks_by_ids(self, **kwargs):
            return [
                type(
                    "Chunk",
                    (),
                    {
                        "group_id": "g1",
                        "doc_id": "d1",
                        "chunk_id": "c1",
                        "index": 0,
                        "text": "chunk text",
                    },
                )()
            ]

    svc = RetrievalService()
    svc._grag = _FakeGRAG()
    svc._pg = FakePG()

    resp = svc.retrieve(
        RetrievalRequest(
            group_id="g1",
            mode="entities",
            query="Alpha",
            include_evidence=True,
        )
    )

    evidence = resp.result["evidence"]
    assert evidence["entity_mentions"][0]["entity_name"] == "Alpha"
    assert evidence["chunks"][0]["chunk_id"] == "c1"
    assert resp.result["meta"]["mode"] == "entities"
    assert resp.result["meta"]["has_evidence"] is True


def test_chunk_keyword_response_includes_agent_friendly_meta() -> None:
    svc = RetrievalService()
    svc._grag = _FakeGRAG()
    svc._pg = _FakePG()

    resp = svc.retrieve(
        RetrievalRequest(
            group_id="g1",
            mode="chunks_keyword",
            query="keyword test",
            top_k=5,
        )
    )

    result = resp.result
    assert result["keyword_hits"][0]["score"] == 1.23
    assert result["meta"]["mode"] == "chunks_keyword"
    assert result["meta"]["requested_top_k"] == 5
    assert result["meta"]["counts"]["keyword_hits"] == 1
    assert result["meta"]["source_modes"] == ["keyword_hits"]
