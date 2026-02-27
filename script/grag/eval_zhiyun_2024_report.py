from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import json

from grag import BuildOptions, GRAG, QueryOptions
from grag.config import get_config_manager
from grag.data_client import get_data_manager
from grag.preprocessing.preprocessing_manager import PreprocessingManager


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    expected_substrings: tuple[str, ...]
    high_keywords: tuple[str, ...]
    low_keywords: tuple[str, ...]


def _cleanup_postgres(*, group_id: str, doc_ids: list[str]) -> None:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for doc_id in doc_ids:
                    cur.execute(
                        "DELETE FROM grag_relations WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_entities WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_chunks WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_documents WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
    finally:
        conn.close()


def _cleanup_milvus(*, collection_name: str, group_id: str, chunk_ids: list[str]) -> None:
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    col = pymilvus.Collection(name=collection_name, using=milvus._alias)
    pks = [f"{group_id}:{cid}" for cid in chunk_ids]
    expr = 'pk in ["' + '", "'.join(pks) + '"]'
    col.delete(expr)
    col.flush()


def _cleanup_milvus_graph_index(*, collection_name: str, group_id: str, doc_ids: list[str]) -> None:
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    if not pymilvus.utility.has_collection(collection_name, using=milvus._alias):
        return
    col = pymilvus.Collection(name=collection_name, using=milvus._alias)
    for doc_id in doc_ids:
        expr = f'group_id == "{group_id}" and doc_id == "{doc_id}"'
        try:
            col.delete(expr)
        except Exception:
            pass
    col.flush()


def _drop_milvus_collection(*, collection_name: str) -> None:
    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")
    try:
        pymilvus.utility.drop_collection(collection_name)
    except Exception:
        pass


def _cleanup_neo4j(*, group_id: str, doc_id: str) -> None:
    dm = get_data_manager()
    driver = dm.get_neo4j_client().get_driver()

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

    db = None
    try:
        db = dm.get_neo4j_client()._get_config().database
    except Exception:
        db = None

    if db:
        with driver.session(database=db) as session:
            session.execute_write(_run)
    else:
        with driver.session() as session:
            session.execute_write(_run)


def _pick_graph_entity_name(*, group_id: str, doc_id: str) -> str | None:
    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT canonical_name FROM grag_entities WHERE group_id=%s AND doc_id=%s LIMIT 1",
                    (group_id, doc_id),
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


def _has_expected(text: str, expected: tuple[str, ...]) -> bool:
    t = (text or "")
    return all(e in t for e in expected)


def _score_hits(hits: list, expected: tuple[str, ...]) -> tuple[int, int]:
    """Return (hit_count, top1_hit)."""
    if not hits:
        return (0, 0)

    hit_any = 0
    for h in hits:
        if _has_expected(getattr(h, "text", "") or "", expected):
            hit_any = 1
            break

    top1 = 1 if _has_expected(getattr(hits[0], "text", "") or "", expected) else 0
    return (hit_any, top1)


def _print_hits(*, title: str, hits: list, expected: tuple[str, ...], top_n: int = 3) -> None:
    hit_any, top1 = _score_hits(hits, expected)
    print(f"\n[{title}] hits={len(hits)} expected={expected} hit_any={hit_any} top1={top1}")
    for i, h in enumerate(hits[:top_n]):
        text = (getattr(h, "text", "") or "").replace("\n", " ")
        text = text[:220]
        doc_id = getattr(h, "doc_id", None)
        chunk_id = getattr(h, "chunk_id", None)
        score = getattr(h, "score", None)
        print(f"  - {i}: doc_id={doc_id} chunk_id={chunk_id} score={score} text={text!r}")


def _short_dict(d: dict, *, max_len: int = 240) -> str:
    try:
        s = json.dumps(d, ensure_ascii=False, sort_keys=True)
    except Exception:
        s = repr(d)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _fmt_node(node: dict) -> str:
    name = node.get("name") or node.get("canonical_name") or node.get("title")
    node_id = node.get("id") or node.get("pk") or node.get("source_id")
    node_type = node.get("type") or node.get("label") or node.get("labels")
    desc = node.get("description") or node.get("summary") or node.get("desc")
    parts = []
    if name:
        parts.append(f"name={name!r}")
    if node_id:
        parts.append(f"id={node_id!r}")
    if node_type:
        parts.append(f"type={node_type!r}")
    if desc:
        d = str(desc)
        if len(d) > 160:
            d = d[:157] + "..."
        parts.append(f"desc={d!r}")
    if node.get("doc_id"):
        parts.append(f"doc_id={node.get('doc_id')!r}")
    if node.get("group_id"):
        parts.append(f"group_id={node.get('group_id')!r}")
    if parts:
        return ", ".join(parts)
    return _short_dict(node)


def _fmt_edge(edge: dict) -> str:
    head = edge.get("head_name") or edge.get("head") or edge.get("source")
    tail = edge.get("tail_name") or edge.get("tail") or edge.get("target")
    rel = edge.get("relation_type") or edge.get("type") or edge.get("label")
    desc = edge.get("description") or edge.get("summary") or edge.get("desc")
    parts = []
    if head or tail or rel:
        parts.append(f"{head!r} -[{rel!r}]-> {tail!r}")
    if desc:
        d = str(desc)
        if len(d) > 160:
            d = d[:157] + "..."
        parts.append(f"desc={d!r}")
    if edge.get("doc_id"):
        parts.append(f"doc_id={edge.get('doc_id')!r}")
    if edge.get("group_id"):
        parts.append(f"group_id={edge.get('group_id')!r}")
    if parts:
        return " ".join(parts)
    return _short_dict(edge)


def _print_graph(*, title: str, graph, top_n: int) -> None:
    if graph is None:
        print(f"\n[{title}] graph=None")
        return

    nodes = list(getattr(graph, "nodes", None) or [])
    edges = list(getattr(graph, "edges", None) or [])

    print(f"\n[{title}] nodes={len(nodes)} edges={len(edges)}")

    if nodes:
        print("  nodes:")
        for i, n in enumerate(nodes[: max(0, int(top_n))]):
            if not isinstance(n, dict):
                print(f"    - {i}: {n!r}")
                continue
            print(f"    - {i}: {_fmt_node(n)}")
        if len(nodes) > int(top_n):
            print(f"    ... ({len(nodes) - int(top_n)} more nodes)")

    if edges:
        print("  edges:")
        for i, e in enumerate(edges[: max(0, int(top_n))]):
            if not isinstance(e, dict):
                print(f"    - {i}: {e!r}")
                continue
            print(f"    - {i}: {_fmt_edge(e)}")
        if len(edges) > int(top_n):
            print(f"    ... ({len(edges) - int(top_n)} more edges)")


def _keywords_to_param(keywords) -> str:
    if keywords is None:
        return ""
    if isinstance(keywords, str):
        ks = [keywords.strip()] if keywords.strip() else []
    else:
        try:
            ks = [str(k).strip() for k in keywords if str(k).strip()]
        except TypeError:
            ks = [str(keywords).strip()] if str(keywords).strip() else []
    if not ks:
        return ""
    if len(ks) == 1:
        # AdvancedRetrievalManager 只在参数中包含逗号时，才认为是“显式 keywords 列表”。
        # 单个关键词也强制带一个逗号，避免走 split_high_low(query) 的默认逻辑。
        return ks[0] + ","
    return ",".join(ks)


def _keywords_to_tuple(keywords) -> tuple[str, ...]:
    if keywords is None:
        return ()
    if isinstance(keywords, str):
        s = keywords.strip()
        return (s,) if s else ()
    try:
        ks = tuple(str(k).strip() for k in keywords if str(k).strip())
        return ks
    except TypeError:
        s = str(keywords).strip()
        return (s,) if s else ()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a DOCX and evaluate retrieval quality across 4 modes.")
    parser.add_argument(
        "--docx",
        type=str,
        default=str(
            Path(__file__).resolve().parents[2]
            / "test"
            / "grag"
            / "test_data"
            / "input"
            / "文档正文：智云科技股份有限公司 2024 年度报告（摘要）.docx"
        ),
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--skip-ingest", action="store_true", default=False)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    parser.add_argument("--group-id", type=str, default="")
    parser.add_argument("--milvus-collection", type=str, default="")
    parser.add_argument("--graph-index-collection", type=str, default="grag_graph_index")
    parser.add_argument("--doc-id", type=str, default="")
    parser.add_argument(
        "--graph-entity",
        type=str,
        default="",
        help="Optional graph entry entity name. If not set, will try to pick one from Postgres by --doc-id.",
    )
    parser.add_argument("--print-graph", action="store_true", default=False)
    parser.add_argument("--graph-top-n", type=int, default=30)
    args = parser.parse_args()

    get_config_manager().initialize()
    dm = get_data_manager()

    print("\n== Connectivity checks ==")
    print("Postgres:", dm.get_postgres_client().test_connection())
    print("Milvus:", dm.get_milvus_client().test_connection())
    print("Neo4j:", dm.get_neo4j_client().test_connection())

    group_id = args.group_id or f"eval_zhiyun_{uuid4().hex[:8]}"
    collection_name = args.milvus_collection or f"eval_zhiyun_{uuid4().hex[:10]}"
    graph_index_collection = args.graph_index_collection

    did_ingest = False

    doc_id = ""
    doc_name = ""
    doc_time = ""
    snippet = ""

    if not args.skip_ingest:
        docx_path = Path(args.docx)
        if not docx_path.exists():
            raise FileNotFoundError(f"DOCX not found: {docx_path}")

        print("\n== Load DOCX ==")
        processor = PreprocessingManager()
        text = processor.process_file(docx_path, use_llm=False)
        if not text.strip():
            raise RuntimeError("Empty extracted text")

        snippet = text[:12000]
        doc_id = f"doc_zhiyun_{uuid4().hex[:8]}"
        doc_name = docx_path.stem
        doc_time = datetime.now(timezone.utc).isoformat()
    else:
        if not str(args.group_id or "").strip():
            raise ValueError("--group-id is required when --skip-ingest is set")
        if not str(args.milvus_collection or "").strip():
            raise ValueError("--milvus-collection is required when --skip-ingest is set")
        doc_id = str(args.doc_id or "").strip()

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

    created_chunk_ids: list[str] = []
    created_doc_ids: list[str] = [doc_id] if doc_id else []

    try:
        highlow = None

        if not args.skip_ingest:
            print("\n== Ingest ==")
            build_res = api.build_kg(
                text=snippet,
                doc_time=doc_time,
                doc_name=doc_name,
                group_id=group_id,
                doc_id=doc_id,
            )
            did_ingest = True
            created_chunk_ids.extend([c.chunk_id for c in build_res.chunks])
            print(f"Ingested doc_id={doc_id} chunks={len(build_res.chunks)} group_id={group_id}")
        else:
            print("\n== Retrieval-only mode (--skip-ingest) ==")
            print(f"Using group_id={group_id}")
            print(f"Using collection_name={collection_name}")
            if doc_id:
                print(f"Using doc_id={doc_id}")

        override_graph_entity = str(args.graph_entity or "").strip() or None
        picked_entity = None
        if override_graph_entity is None and doc_id:
            picked_entity = _pick_graph_entity_name(group_id=group_id, doc_id=doc_id)

        if override_graph_entity:
            print(f"Override graph entity (--graph-entity): {override_graph_entity!r}")
        elif picked_entity:
            print(f"Picked entity from postgres (info only): {picked_entity!r}")
        else:
            print("No graph entity override provided")

        cases: list[EvalCase] = [
            EvalCase(
                name="local_dividend",
                query="分红预案每10股派发多少现金红利？",
                expected_substrings=("每 10 股", "2.5"),
                high_keywords=(),
                low_keywords=("分红预案", "现金红利", "每10股"),
            ),
            EvalCase(
                name="global_major_events",
                query="公司2024年有哪些重大事项？",
                expected_substrings=("收购", "诉讼"),
                high_keywords=("重大事项", "事件"),
                low_keywords=(),
            ),
        ]

        top_k = int(args.top_k)

        print("\n== Retrieval evaluation ==")
        for c in cases:
            print("\n" + "-" * 80)
            print(f"Case={c.name} query={c.query!r} expected={c.expected_substrings}")
            high_kw = _keywords_to_tuple(getattr(c, "high_keywords", ()))
            low_kw = _keywords_to_tuple(getattr(c, "low_keywords", ()))
            print(f"  high_keywords={high_kw}")
            print(f"  low_keywords={low_kw}")

            kw = api.chunks_keyword(group_id=group_id, query=c.query, top_k=top_k, rerank_enabled=False)
            _print_hits(title=f"ChunksKeyword/{c.name}", hits=kw.keyword_hits, expected=c.expected_substrings)

            nat = api.chunks_vector(group_id=group_id, query=c.query, top_k=top_k, rerank_enabled=False)
            _print_hits(title=f"ChunksVector/{c.name}", hits=nat.semantic_hits, expected=c.expected_substrings)

            local_param = _keywords_to_param(low_kw)
            global_param = _keywords_to_param(high_kw)

            # 若用户显式传了 --graph-entity，则优先使用它（它会同时影响 local/global）。
            if override_graph_entity:
                local_param = override_graph_entity
                global_param = override_graph_entity

            if local_param:
                loc = api.local(
                    group_id=group_id,
                    query=c.query,
                    graph_entity_name=local_param,
                    graph_max_depth=2,
                    graph_limit=20,
                    top_k=top_k,
                    rerank_enabled=False,
                )
                g_nodes = len(loc.local_graph.nodes) if loc.local_graph else 0
                g_edges = len(loc.local_graph.edges) if loc.local_graph else 0
                print(f"\n[Local/{c.name}] graph_nodes={g_nodes} graph_edges={g_edges}")
                if args.print_graph:
                    _print_graph(title=f"LocalGraph/{c.name}", graph=loc.local_graph, top_n=int(args.graph_top_n))

            if global_param:
                glo = api.global_(
                    group_id=group_id,
                    query=c.query,
                    graph_entity_name=global_param,
                    graph_max_depth=2,
                    graph_limit=20,
                    top_k=top_k,
                    rerank_enabled=False,
                )
                g_nodes = len(glo.global_graph.nodes) if glo.global_graph else 0
                g_edges = len(glo.global_graph.edges) if glo.global_graph else 0
                print(f"[Global/{c.name}] graph_nodes={g_nodes} graph_edges={g_edges}")
                if args.print_graph:
                    _print_graph(title=f"GlobalGraph/{c.name}", graph=glo.global_graph, top_n=int(args.graph_top_n))

        print("\n== Done ==")
        print(f"group_id={group_id}")
        print(f"collection_name={collection_name}")
        print(f"doc_id={doc_id}")
        return 0

    finally:
        if args.no_cleanup:
            print("\n== Skip cleanup (--no-cleanup) ==")
            return 0

        if not did_ingest:
            print("\n== Skip cleanup (retrieval-only mode) ==")
            return 0

        print("\n== Cleanup ==")
        try:
            if created_chunk_ids:
                _cleanup_milvus(collection_name=collection_name, group_id=group_id, chunk_ids=created_chunk_ids)
        except Exception as e:
            print("cleanup milvus failed:", e)

        try:
            _cleanup_milvus_graph_index(collection_name=graph_index_collection, group_id=group_id, doc_ids=created_doc_ids)
        except Exception as e:
            print("cleanup milvus graph index failed:", e)

        for did in created_doc_ids:
            try:
                _cleanup_neo4j(group_id=group_id, doc_id=did)
            except Exception as e:
                print("cleanup neo4j failed:", e)

        try:
            _cleanup_postgres(group_id=group_id, doc_ids=created_doc_ids)
        except Exception as e:
            print("cleanup postgres failed:", e)

        try:
            _drop_milvus_collection(collection_name=collection_name)
        except Exception as e:
            print("drop milvus collection failed:", e)


if __name__ == "__main__":
    raise SystemExit(main())
