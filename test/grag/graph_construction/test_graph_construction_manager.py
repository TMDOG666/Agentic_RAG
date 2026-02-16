import sys
from pathlib import Path

import json
import os
from datetime import datetime, timezone

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.graph_construction_manager import GraphConstructionManager
from grag.config import get_settings


SAMPLE_ENTITY_RELATION_RAW = """entity<|SEP|>张三<|SEP|>人物<|SEP|>文档中的人物
entity<|SEP|>李四<|SEP|>人物<|SEP|>另一位人物
relation<|SEP|>张三<|SEP|>李四<|SEP|>朋友关系<|SEP|>friend<|SEP|>8
<|DONE|>
"""


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

def test_graph_construction_manager_end_to_end_from_chinese_outline() -> None:
    """端到端跑完整流程。

    输入：test_data/input/chinese_outline.txt
    输出：test_data/output/chinese_outline.graph_construction_manager.json

    默认使用真实 LLM；如果你只想离线验证流程串联，可设置：
        GRAG_USE_FAKE_LLM=1
    """

    use_fake_llm = os.environ.get("GRAG_USE_FAKE_LLM") == "1"

    if use_fake_llm:
        def fake_coref_chat(_prompt: str) -> str:
            return "[]"

        def fake_entity_relation_chat(_prompt: str) -> str:
            return SAMPLE_ENTITY_RELATION_RAW

        def fake_fusion_chat(_prompt: str) -> str:
            # entity_resolution_knowledge_fusion 期望 LLM 输出为 JSON
            return """[{\"canonical_name\":\"张三\",\"type\":\"人物\",\"aliases\":[\"张三\"],\"description\":\"人物\"}]"""

        def fake_embedding_fn(texts: list[str], _provider: str) -> list[list[float]]:
            # 为每条输入返回一个固定维度向量，避免真实 embedding 调用
            return [[0.0, 0.0, float(i)] for i in range(len(texts))]

        manager = GraphConstructionManager(
            coref_llm_chat_fn=fake_coref_chat,
            entity_relation_llm_chat_fn=fake_entity_relation_chat,
            fusion_llm_chat_fn=fake_fusion_chat,
            embedding_fn=fake_embedding_fn,
        )
    else:
        manager = GraphConstructionManager(
            coref_llm_chat_fn=None,
            entity_relation_llm_chat_fn=None,
        )

    stem, text = _read_input_text("chinese_outline.txt")
    doc_time = datetime.now(timezone.utc).isoformat()
    result = manager.run(text=text, doc_time=doc_time, doc_name=stem)

    _write_outputs(stem, _result_to_jsonable(result))




def run_tests() -> bool:
    tests = [
        ("chinese_outline", "端到端 chinese_outline", test_graph_construction_manager_end_to_end_from_chinese_outline),
    ]

    # 允许只跑某一个测试，便于你做“真实端到端”验证。
    # 例如：
    #   GRAG_RUN_TEST=chinese_outline
    run_only = os.environ.get("GRAG_RUN_TEST")
    if run_only:
        run_only = run_only.strip().lower()
        tests = [t for t in tests if t[0] == run_only]

    results: list[tuple[str, bool, str]] = []
    for key, name, fn in tests:
        try:
            fn()
            print(f"[PASS] {key} - {name}")
            results.append((name, True, ""))
        except Exception as e:
            print(f"[FAIL] {key} - {name}: {repr(e)}")
            results.append((name, False, repr(e)))

    if not results:
        print(f"No tests selected. GRAG_RUN_TEST={os.environ.get('GRAG_RUN_TEST')!r}")
        return False

    return all(ok for _, ok, _ in results)


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)
