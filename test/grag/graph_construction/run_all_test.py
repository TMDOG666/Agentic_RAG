from pathlib import Path

import asyncio
import json
import os
import uuid

from grag.graph_construction.chunker import SemanticChunker
from grag.graph_construction.coreference_resolver import CoreferenceResolver
from grag.graph_construction.entity_relation_extractor import Chunk, EntityRelationExtractor


def _paths() -> tuple[Path, Path, Path]:
    base = Path(__file__).parent / "test_data"
    input_dir = base / "input"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, input_dir, output_dir


def _read_any_input_text() -> tuple[str, str]:
    _, input_dir, _ = _paths()
    candidates = list(input_dir.glob("*.txt")) + list(input_dir.glob("*.md"))
    if not candidates:
        raise RuntimeError(f"No input files found under: {input_dir}")
    p = candidates[0]
    return p.stem, p.read_text(encoding="utf-8")


def _fake_llm_chat(_prompt: str) -> str:
    return "\n".join(
        [
            "entity<|SEP|>演示实体<|SEP|>概念<|SEP|>用于端到端测试",
            "relation<|SEP|>演示实体<|SEP|>演示实体<|SEP|>自环关系<|SEP|>测试<|SEP|>5",
            "<|DONE|>",
        ]
    )


def _fake_coref_chat(_prompt: str) -> str:
    return "[]"


def test_chunk_and_extract_end_to_end_smoke() -> None:
    """端到端 smoke：指代消解 -> 分块 -> 实体关系抽取。

    该测试只验证“管线可串联 + 输出结构基本正确”，不依赖任何外部 LLM / embedding。

    保留写文件输出，方便你在 test_data/output 下快速目视检查。
    """

    _base, _input_dir, output_dir = _paths()
    stem = "smoke"
    text = "演示实体与演示实体存在关系。他们发生了某件事。"

    coref_resolver = CoreferenceResolver(llm_chat_fn=_fake_coref_chat)
    extractor = EntityRelationExtractor(llm_chat_fn=_fake_llm_chat)

    doc_coref = asyncio.run(coref_resolver.resolve_text(text))
    assert doc_coref.error is None

    chunker = SemanticChunker(max_token_threshold=50, min_token_threshold=1)
    chunks_text = chunker.chunk(doc_coref.resolved_text)
    assert isinstance(chunks_text, list)
    assert len(chunks_text) >= 1

    chunk_objs: list[Chunk] = []
    for i, t in enumerate(chunks_text, 1):
        chunk_id = f"chunk_{i}_{uuid.uuid4().hex}"
        chunk_objs.append(Chunk(chunk_id=chunk_id, text=t))

    results = asyncio.run(extractor.extract_many(chunk_objs))
    assert isinstance(results, list)
    assert len(results) == len(chunk_objs)
    assert all(r.error is None for r in results)
    assert all(bool(r.entity_relation_raw) for r in results)

    payload = [
        {
            "chunk_id": r.chunk_id,
            "text": r.text,
            "document_coreference_raw": doc_coref.coreference_raw,
            "document_coref_error": doc_coref.error,
            "entity_relation_raw": r.entity_relation_raw,
            "error": r.error,
        }
        for r in results
    ]

    out_path = output_dir / f"{stem}.chunk_and_extract.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
