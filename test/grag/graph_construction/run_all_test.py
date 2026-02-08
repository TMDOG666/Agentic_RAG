import sys
from pathlib import Path

import asyncio
import json
import os
import uuid

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.chunker import SemanticChunker
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


def main() -> None:
    base, _input_dir, output_dir = _paths()
    stem, text = _read_any_input_text()

    # Step 1) 分块：生成 List[str]
    chunker = SemanticChunker()
    chunks_text = chunker.chunk(text)

    # Step 2) 组装成对象列表（chunk_{顺序}_{uuid}）
    chunk_objs: list[Chunk] = []
    for i, t in enumerate(chunks_text, 1):
        chunk_id = f"chunk_{i}_{uuid.uuid4().hex}"
        chunk_objs.append(Chunk(chunk_id=chunk_id, text=t))

    # Step 3) 实体关系抽取（并发处理）
    # 默认使用真实 LLM；只有在你显式指定 GRAG_USE_FAKE_LLM=1 时，才使用 fake LLM。
    use_fake_llm = os.environ.get("GRAG_USE_FAKE_LLM") == "1"
    if use_fake_llm:
        print("[INFO] Using FAKE LLM (GRAG_USE_FAKE_LLM=1)")
        extractor = EntityRelationExtractor(llm_chat_fn=_fake_llm_chat)
    else:
        print("[INFO] Using REAL LLM via grag.model.llm_client.LLMClient")
        print("[INFO] If you see API key errors, set the provider key env var (e.g. SILICONFLOW_API_KEY)")
        extractor = EntityRelationExtractor(llm_chat_fn=None)

    results = asyncio.run(extractor.extract_many(chunk_objs))

    # Step 4) 组织输出结构
    payload = []
    for r in results:
        payload.append(
            {
                "chunk_id": r.chunk_id,
                "text": r.text,
                "entity_relation_raw": r.entity_relation_raw,
                "error": r.error,
            }
        )

    out_path = output_dir / f"{stem}.chunk_and_extract.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote: {out_path}")


if __name__ == "__main__":
    main()
