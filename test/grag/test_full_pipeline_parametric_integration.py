from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import pytest

from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.entrypoint import BuildOptions, GRAG, QueryOptions
from grag.storage.storage_impl import DataClientGraphStorage

from test.grag.retrieval.test_full_retrieval_integration import (
    _cleanup_milvus,
    _cleanup_milvus_graph_index,
    _cleanup_neo4j,
    _cleanup_postgres,
    _drop_milvus_collection,
    _pick_graph_entity_name,
    _pick_keyword_query,
    _pick_semantic_query,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings(
        "ignore:Pydantic V1 style `@validator` validators are deprecated.*:DeprecationWarning"
    ),
]


def _jsonable(x: Any):
    if is_dataclass(x):
        return asdict(x)
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "__dict__"):
        return _jsonable(vars(x))
    return str(x)


def _maybe_print_json(*, title: str, payload: Any, enabled: bool) -> None:
    if not enabled:
        return
    print(f"\n[{title}] full_result(json)=")
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2))


def _parse_modes(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in (raw or "").split(",")]
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if p in {"vector", "native"}:
            out.append("native")
        else:
            out.append(p)
    # 去重但保持顺序
    dedup: list[str] = []
    seen: set[str] = set()
    for m in out:
        if m in seen:
            continue
        seen.add(m)
        dedup.append(m)
    return dedup


def _ensure_collection_name_valid(name: str) -> bool:
    if not name:
        return False
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def test_full_pipeline_parametric(real_doc_texts, pytestconfig) -> None:
    """一个可参数控制的端到端 integration 测试。

    目标：用一条测试用例覆盖以下操作（可按参数选择执行哪些步骤）：
    - 可选：入库（Postgres + Milvus chunk collection + Milvus graph_index + Neo4j）
    - 可选：清理（按本次 run 创建的 doc/chunk 删除）
    - 可选：检索（keyword/native/local/global）

    CLI 参数（见 test/conftest.py）：
    - --pipeline-ingest
    - --pipeline-cleanup（强制清理，覆盖 --no-cleanup）
    - --pipeline-modes=keyword,native,local,global
    - --pipeline-docs=2
    - --pipeline-graph-index-collection（默认 grag_graph_index）

    复用已有参数：
    - --pause
    - --no-cleanup
    - --print-results

    说明：
    - 该用例默认不“自动入库”（避免每次跑都写 DB）。如果希望跑全链路，请加 --pipeline-ingest。
    - 如果不入库，你需要自己提供现成的 group/collection；否则本测试会 skip。
      （目前为了不引入更多参数，我们建议在本测试中总是使用 --pipeline-ingest。）
    """

    get_config_manager().initialize()
    dm = get_data_manager()

    assert dm.get_postgres_client().test_connection() is True
    assert dm.get_milvus_client().test_connection() is True
    assert dm.get_neo4j_client().test_connection() is True

    print_enabled = bool(pytestconfig.getoption("print_results"))

    pipeline_ingest = bool(pytestconfig.getoption("pipeline_ingest"))
    pipeline_cleanup_force = bool(pytestconfig.getoption("pipeline_cleanup"))
    no_cleanup = bool(pytestconfig.getoption("no_cleanup"))
    pause_s = float(pytestconfig.getoption("pause") or 0)

    modes = _parse_modes(str(pytestconfig.getoption("pipeline_modes") or ""))
    docs_n = max(1, int(pytestconfig.getoption("pipeline_docs") or 2))

    graph_index_collection = str(pytestconfig.getoption("pipeline_graph_index_collection") or "").strip()
    if not graph_index_collection:
        graph_index_collection = "grag_graph_index"

    # 本测试采用“自给自足”策略：如果 ingest，则新建 group/collection；否则 skip。
    if not pipeline_ingest:
        pytest.skip("pipeline-ingest disabled; pass --pipeline-ingest to run end-to-end")

    group_id = f"pytest_pipe_{uuid4().hex[:8]}"
    collection_name = f"pytest_pipe_{uuid4().hex[:10]}"

    if not _ensure_collection_name_valid(collection_name):
        pytest.skip("Generated milvus collection name invalid")

    storage = DataClientGraphStorage(
        milvus_collection_name=collection_name,
        milvus_graph_index_collection_name=graph_index_collection,
        milvus_upsert_strategy="delete_then_insert",
    )

    api = GRAG(
        build_options=BuildOptions(
            milvus_collection_name=collection_name,
            milvus_upsert_strategy="delete_then_insert",
            milvus_graph_index_collection_name=graph_index_collection,
        ),
        query_options=QueryOptions(
            milvus_collection_name=collection_name,
            milvus_graph_index_collection_name=graph_index_collection,
        ),
    )

    created_doc_ids: list[str] = []
    created_chunk_ids: list[str] = []

    first_doc_id: Optional[str] = None
    example_chunk_text: str = ""

    try:
        assert len(real_doc_texts) >= docs_n

        # 1) 入库
        for i, (p, text) in enumerate(real_doc_texts[:docs_n]):
            doc_id = f"doc_{i}_{uuid4().hex[:8]}"
            doc_name = p.stem
            doc_time = datetime.now(timezone.utc).isoformat()
            snippet = (text or "")[:6000]

            result = api.build_kg(
                text=snippet,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
            )

            created_doc_ids.append(doc_id)
            created_chunk_ids.extend([c.chunk_id for c in result.chunks])

            if first_doc_id is None:
                first_doc_id = doc_id
                example_chunk_text = result.chunks[0].text or ""

        assert first_doc_id is not None

        # 2) 检索
        keyword_q = _pick_keyword_query(example_chunk_text)
        semantic_q = _pick_semantic_query(example_chunk_text)

        # graph_entity_name：优先从本次入库抽取的实体中取一个
        entity_name = _pick_graph_entity_name(group_id=group_id, doc_id=first_doc_id)

        for m in modes:
            if m == "keyword":
                print("\n[Keyword] query=", repr(keyword_q))
                res = api.query(
                    group_id=group_id,
                    query=keyword_q,
                    mode="keyword",
                    top_k=10,
                    rerank_enabled=False,
                )
                print("[Keyword] hits=", len(res.keyword_hits))
                assert isinstance(res.keyword_hits, list)
                assert len(res.keyword_hits) > 0
                _maybe_print_json(title="Keyword", payload=res, enabled=print_enabled)

            elif m == "native":
                print("\n[Native] query=", repr(semantic_q))
                res = api.query(
                    group_id=group_id,
                    query=semantic_q,
                    mode="native",
                    top_k=10,
                    rerank_enabled=False,
                )
                print("[Native] semantic_hits=", len(res.semantic_hits))
                assert isinstance(res.semantic_hits, list)
                assert len(res.semantic_hits) > 0
                _maybe_print_json(title="Native", payload=res, enabled=print_enabled)

            elif m == "local":
                # local/global 使用 high>low 协议：此处沿用 existing tests 的简化用法
                if not entity_name:
                    pytest.skip("No entity extracted for local retrieval in this run")
                highlow = f"{entity_name}>{entity_name}"
                print("\n[Local] highlow=", repr(highlow), "query=", repr(semantic_q))
                res = api.query(
                    group_id=group_id,
                    query=semantic_q,
                    graph_entity_name=highlow,
                    mode="local",
                    graph_max_depth=2,
                    graph_limit=50,
                    rerank_enabled=False,
                )
                assert res.local_graph is not None
                print("[Local] nodes=", len(res.local_graph.nodes), "edges=", len(res.local_graph.edges))
                _maybe_print_json(title="Local", payload=res, enabled=print_enabled)

            elif m == "global":
                if not entity_name:
                    pytest.skip("No entity extracted for global retrieval in this run")
                highlow = f"{entity_name}>{entity_name}"
                print("\n[Global] highlow=", repr(highlow), "query=", repr(semantic_q))
                res = api.query(
                    group_id=group_id,
                    query=semantic_q,
                    graph_entity_name=highlow,
                    mode="global",
                    graph_max_depth=2,
                    graph_limit=50,
                    rerank_enabled=False,
                )
                assert res.global_graph is not None
                print("[Global] nodes=", len(res.global_graph.nodes), "edges=", len(res.global_graph.edges))
                _maybe_print_json(title="Global", payload=res, enabled=print_enabled)

            else:
                raise ValueError(f"Unsupported pipeline mode: {m}")

    finally:
        if pause_s > 0:
            time.sleep(pause_s)

        do_cleanup = pipeline_cleanup_force or (not no_cleanup)
        if not do_cleanup:
            return

        if created_chunk_ids:
            _cleanup_milvus(collection_name=collection_name, group_id=group_id, chunk_ids=created_chunk_ids)

        _cleanup_milvus_graph_index(
            collection_name=graph_index_collection,
            group_id=group_id,
            doc_ids=created_doc_ids,
        )

        for doc_id in created_doc_ids:
            _cleanup_neo4j(group_id=group_id, doc_id=doc_id)

        if created_doc_ids:
            _cleanup_postgres(group_id=group_id, doc_ids=created_doc_ids)

        _drop_milvus_collection(collection_name=collection_name)
