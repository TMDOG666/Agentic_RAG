from pathlib import Path

import json
from datetime import datetime, timezone

from grag.graph_construction.graph_construction_manager import GraphConstructionManager
from grag.config import ProviderType, get_config_manager
import pytest


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    input_dir = base / "input"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.graph_construction_manager.json").write_text(content, encoding="utf-8")


def _read_input_text(filename: str) -> tuple[str, str]:
    input_dir, _ = _paths()
    p = input_dir / filename
    return p.stem, p.read_text(encoding="utf-8")


def _result_to_jsonable(result) -> dict:
    fusion_json = None
    try:
        if result.graph and isinstance(result.graph, dict) and "intra_document_fusion" in result.graph:
            fusion = result.graph["intra_document_fusion"]
            fusion_json = {
                "fused_entities": [fe.__dict__ for fe in fusion.fused_entities],
                "rewritten_relations": [r.__dict__ for r in fusion.rewritten_relations],
                "alias_to_canonical": dict(fusion.alias_to_canonical),
                "errors": list(fusion.errors),
                # clusters 很大，这里只写一个摘要，方便你快速确认“文档级聚类/融合”确实发生。
                "clusters": [
                    {
                        "cluster_id": c.cluster_id,
                        "size": len(c.members),
                        "members": [m.name for m in c.members],
                    }
                    for c in fusion.clusters
                ],
            }
    except Exception:
        fusion_json = {"error": "failed to serialize intra_document_fusion"}

    return {
        "doc_name": result.doc_name,
        "doc_time": result.doc_time,
        "original_text": result.original_text,
        "coreference": {
            "text": result.coreference.text,
            "coreference_raw": result.coreference.coreference_raw,
            "resolved_text": result.coreference.resolved_text,
            "error": result.coreference.error,
        },
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "entity_relation_raw": c.entity_relation_raw,
                "error": c.error,
                "parsed": {
                    "entities": [e.__dict__ for e in c.parsed.entities],
                    "relations": [r.__dict__ for r in c.parsed.relations],
                    "errors": c.parsed.errors,
                },
            }
            for c in result.chunks
        ],
        "graph": {
            "intra_document_fusion": fusion_json,
        },
    }


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(x in url_lower for x in ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"])


def _ensure_real_llm_ready() -> None:
    settings = get_config_manager().get_settings()
    llm_cfg = settings.get_provider_config(ProviderType.LLM)
    llm_api_key = (
        __import__("os").environ.get("GRAG_LLM_API_KEY")
        or __import__("os").environ.get(getattr(llm_cfg, "api_key_env", "") or "")
    )
    if not llm_api_key and llm_cfg.base_url and not _is_local_url(llm_cfg.base_url):
        pytest.skip("LLM API key missing for non-local base_url")


@pytest.mark.integration
def test_graph_construction_manager_end_to_end_from_chinese_outline(real_doc_texts) -> None:
    """端到端跑完整流程。

    输入：test_data/input/chinese_outline.txt
    输出：test_data/output/chinese_outline.graph_construction_manager.json
    """

    _ensure_real_llm_ready()

    manager = GraphConstructionManager()

    for p, text in real_doc_texts:
        stem = p.stem
        doc_time = datetime.now(timezone.utc).isoformat()
        snippet = text[:4000]
        result = manager.run(text=snippet, doc_time=doc_time, doc_name=stem)
        assert result.doc_name == stem
        assert result.doc_time == doc_time
        assert isinstance(result.chunks, list)
        _write_outputs(stem, _result_to_jsonable(result))
