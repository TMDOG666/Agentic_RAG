"""End-to-end API flow test for the FastAPI backend.

This test is intentionally "black-box": it talks to a running FastAPI server over HTTP.

How to run:
- Start API server (in another terminal):
  - python -m uvicorn api.main:app --port 8000
- Then run with pytest from repo root:
  - pytest -m integration -s test/api/test_api_flow.py

Notes:
- This test uses real external dependencies behind the API (DB/VectorDB/Neo4j/LLM if enabled).
- The test prints retrieval outputs to help you validate the full pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


try:
    import requests
except ImportError as e:  # pragma: no cover
    requests = None
    _requests_import_error = e


@dataclass(frozen=True)
class _DocSpec:
    group_id: str
    docx_path: Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


def _base_url(pytestconfig) -> str:
    # Keep this as CLI option to match the repository's existing pytest style.
    # (The repo README suggests not controlling tests via env vars.)
    url = (pytestconfig.getoption("--api-base-url", default="") or "").strip()
    return url or "http://127.0.0.1:8080"


def _post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    assert requests is not None
    r = requests.post(f"{base_url}{path}", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


def _post_multipart(
    base_url: str,
    path: str,
    *,
    params: dict[str, Any],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    assert requests is not None
    files = {file_field: (filename, file_bytes, content_type)}
    r = requests.post(f"{base_url}{path}", params=params, files=files, timeout=600)
    r.raise_for_status()
    return r.json()


def _delete(base_url: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    assert requests is not None
    r = requests.delete(f"{base_url}{path}", params=params, timeout=600)
    r.raise_for_status()
    return r.json()
@pytest.mark.integration
def test_api_full_flow_create_ingest_retrieve(pytestconfig):
    if requests is None:
        pytest.skip(f"requests missing: {_requests_import_error}")

    base_url = _base_url(pytestconfig)

    input_dir = Path(__file__).resolve().parent / "test_data" / "input"
    assert input_dir.exists(), f"input_dir not found: {input_dir}"

    group_a = "api_test_group_zhiyun"
    group_b = "api_test_group_yujin"

    docs: list[_DocSpec] = [
        _DocSpec(group_id=group_a, docx_path=input_dir / "文档正文：智云科技股份有限公司 2024 年度报告（摘要）.docx"),
        _DocSpec(group_id=group_a, docx_path=input_dir / "文档正文：智云科技股份有限公司 2025 年度报告（摘要）.docx"),
        _DocSpec(group_id=group_b, docx_path=input_dir / "余烬时代的神谕.docx"),
    ]

    created_doc_ids: list[tuple[str, str]] = []  # (group_id, doc_id)

    # 1) Create two groups
    print("\n=== [1] Create groups ===")
    _post_json(
        base_url,
        "/groups-admin",
        {"group_id": group_a, "group_name": "智云年报组", "group_desc": "API 集成测试：两份年报"},
    )
    _post_json(
        base_url,
        "/groups-admin",
        {"group_id": group_b, "group_name": "余烬时代组", "group_desc": "API 集成测试：一份小说"},
    )
    print(f"Created groups: {group_a}, {group_b}")

    # 2) Ingest 3 documents
    print("\n=== [2] Ingest uploads ===")
    for d in docs:
        assert d.docx_path.exists(), f"docx not found: {d.docx_path}"
        ingest_out = _post_multipart(
            base_url,
            "/ingest/upload",
            params={
                "group_id": d.group_id,
                "doc_time": _utc_now_iso(),
                "standardize": "false",
            },
            file_field="file",
            filename=d.docx_path.name,
            file_bytes=d.docx_path.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        print(f"Ingested: group={d.group_id}, file={d.docx_path.name}")
        print(_pretty(ingest_out))
        created_doc_ids.append((d.group_id, str(ingest_out.get("doc_id"))))

    # 3) Run retrieval modes and print results
    print("\n=== [3] Retrieval (all modes) ===")

    def run_mode(payload: dict[str, Any]) -> dict[str, Any]:
        r = _post_json(base_url, "/retrieval", payload)
        print(f"\n--- mode={payload.get('mode')} group={payload.get('group_id')} ---")
        print(_pretty(r))
        return r

    # 3.1 chunks_vector / chunks_keyword
    run_mode({"group_id": group_a, "mode": "chunks_vector", "query": "智云 科技 年度报告", "top_k": 5})
    run_mode({"group_id": group_a, "mode": "chunks_keyword", "query": "年度报告", "top_k": 5})

    run_mode({"group_id": group_b, "mode": "chunks_vector", "query": "神谕 余烬 时代", "top_k": 5})
    run_mode({"group_id": group_b, "mode": "chunks_keyword", "query": "神谕", "top_k": 5})

    # 3.2 entities / relations (vector over graph_index)
    entities_a = run_mode({"group_id": group_a, "mode": "entities", "query": "智云 科技", "top_k": 10}).get("result", {}).get("entities")
    relations_a = run_mode({"group_id": group_a, "mode": "relations", "query": "主营业务", "top_k": 10}).get("result", {}).get("relations")

    entities_b = run_mode({"group_id": group_b, "mode": "entities", "query": "神谕", "top_k": 10}).get("result", {}).get("entities")
    relations_b = run_mode({"group_id": group_b, "mode": "relations", "query": "人物", "top_k": 10}).get("result", {}).get("relations")

    # 3.3 relations_by_entities / entities_by_relations (Neo4j graph primitives)
    def pick_entity_names(entities: Any) -> list[str]:
        if not isinstance(entities, list):
            return []
        out: list[str] = []
        for e in entities:
            if not isinstance(e, dict):
                continue
            name = e.get("canonical_name") or e.get("name") or e.get("entity_name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
            if len(out) >= 3:
                break
        return out

    def pick_relation_ids(relations: Any) -> list[str]:
        if not isinstance(relations, list):
            return []
        out: list[str] = []
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            rid = rel.get("relation_id") or rel.get("id")
            if isinstance(rid, str) and rid.strip():
                out.append(rid.strip())
            if len(out) >= 3:
                break
        return out

    entity_names_a = pick_entity_names(entities_a)
    if entity_names_a:
        run_mode({"group_id": group_a, "mode": "relations_by_entities", "entity_names": entity_names_a, "limit": 50})

    relation_ids_a = pick_relation_ids(relations_a)
    if relation_ids_a:
        run_mode({"group_id": group_a, "mode": "entities_by_relations", "relation_ids": relation_ids_a, "limit": 50})

    entity_names_b = pick_entity_names(entities_b)
    if entity_names_b:
        run_mode({"group_id": group_b, "mode": "relations_by_entities", "entity_names": entity_names_b, "limit": 50})

    relation_ids_b = pick_relation_ids(relations_b)
    if relation_ids_b:
        run_mode({"group_id": group_b, "mode": "entities_by_relations", "relation_ids": relation_ids_b, "limit": 50})

    # 4) Cleanup (optional)
    no_cleanup = bool(
        pytestconfig.getoption("--api-no-cleanup", default=False)
        or pytestconfig.getoption("--no-cleanup", default=False)
    )
    if no_cleanup:
        print("\n=== [4] Cleanup skipped (--api-no-cleanup) ===")
        return

    print("\n=== [4] Cleanup (delete documents then groups) ===")
    for group_id, doc_id in created_doc_ids:
        if doc_id:
            _delete(base_url, f"/documents/{doc_id}", params={"group_id": group_id})
            print(f"Deleted document: group={group_id}, doc_id={doc_id}")

    _delete(base_url, f"/groups-admin/{group_a}")
    _delete(base_url, f"/groups-admin/{group_b}")
    print(f"Deleted groups: {group_a}, {group_b}")
