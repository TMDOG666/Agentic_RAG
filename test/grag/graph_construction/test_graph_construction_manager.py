import sys
from pathlib import Path

import json

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.graph_construction_manager import GraphConstructionManager


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.graph_construction_manager.json").write_text(content, encoding="utf-8")


SAMPLE_ENTITY_RELATION_RAW = "\n".join(
    [
        "entity<|SEP|>加勒特公爵<|SEP|>人物<|SEP|>北境守护者，在绝冬城被刺杀。",
        "entity<|SEP|>绝冬城<|SEP|>地点<|SEP|>加勒特公爵遇刺的地点。",
        "relation<|SEP|>加勒特公爵<|SEP|>绝冬城<|SEP|>加勒特公爵在绝冬城驻守并遇害。<|SEP|>位于/遇害地<|SEP|>10",
        "<|DONE|>",
    ]
)


def test_graph_construction_manager_pipeline_wiring() -> None:
    def fake_coref_chat(_prompt: str) -> str:
        return "[]"

    def fake_entity_relation_chat(_prompt: str) -> str:
        return SAMPLE_ENTITY_RELATION_RAW

    manager = GraphConstructionManager(
        coref_llm_chat_fn=fake_coref_chat,
        entity_relation_llm_chat_fn=fake_entity_relation_chat,
    )

    text = "这是一个很短的故事。他走进了绝冬城。"
    result = manager.run(text=text, doc_time="2026-02-09T00:00:00Z", doc_name="demo")

    assert result.doc_name == "demo"
    assert result.doc_time
    assert result.original_text == text
    assert result.coreference.error is None
    assert result.coreference.resolved_text

    assert isinstance(result.chunks, list)
    assert len(result.chunks) >= 1

    first = result.chunks[0]
    assert first.parsed.entities
    assert first.parsed.relations

    _write_outputs(
        "pipeline_wiring",
        {
            "doc_name": result.doc_name,
            "doc_time": result.doc_time,
            "coreference": {
                "error": result.coreference.error,
                "coreference_raw": result.coreference.coreference_raw,
            },
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "error": c.error,
                    "parsed": {
                        "entities": [e.__dict__ for e in c.parsed.entities],
                        "relations": [r.__dict__ for r in c.parsed.relations],
                        "errors": c.parsed.errors,
                    },
                }
                for c in result.chunks
            ],
        },
    )


def run_tests() -> bool:
    tests = [
        ("流程串联", test_graph_construction_manager_pipeline_wiring),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, fn in tests:
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:
            results.append((name, False, repr(e)))

    return all(ok for _, ok, _ in results)


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)
