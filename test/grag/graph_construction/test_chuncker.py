import sys
from pathlib import Path

import json
import traceback
import pytest

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.chunker import SemanticChunker


def _paths() -> tuple[Path, Path, Path]:
    base = Path(__file__).parent / "test_data"
    input_dir = base / "input"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def _read(name: str) -> str:
    input_dir, _ = _paths()
    p = input_dir / name
    return p.read_text(encoding="utf-8")


def _write_outputs(stem: str, chunks: list[str]) -> None:
    _, output_dir = _paths()
    payload = {
        "source": stem,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": i,
                "text": c,
                "token_count": len(c.split()),
            }
            for i, c in enumerate(chunks)
        ],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.chunks.json").write_text(content, encoding="utf-8")


def test_markdown_semantic_chunking() -> None:
    text = _read("markdown_semantic.md")
    chunker = SemanticChunker(max_token_threshold=20, min_token_threshold=1)
    chunks = chunker.chunk(text)

    assert isinstance(chunks, list)
    assert len(chunks) >= 2
    assert any(c.lstrip().startswith("# 第一章") for c in chunks)
    assert any(c.lstrip().startswith("# 第二章") for c in chunks)

    _write_outputs("markdown_semantic", chunks)


def test_chinese_outline_chunking() -> None:
    text = _read("chinese_outline.txt")
    chunker = SemanticChunker(max_token_threshold=20, min_token_threshold=1)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert any(c.lstrip().startswith("第一章") for c in chunks)
    assert any(c.lstrip().startswith("第二章") for c in chunks)

    _write_outputs("chinese_outline", chunks)


def test_fallback_paragraphs_chunking() -> None:
    text = _read("fallback_paragraphs.txt")
    chunker = SemanticChunker(max_token_threshold=20, min_token_threshold=1)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert not any(c.lstrip().startswith("#") for c in chunks)
    assert "没有任何标题" in chunks[0]

    _write_outputs("fallback_paragraphs", chunks)


def test_complex_markdown_long_chunking() -> None:
    text = _read("complex_markdown_long.txt")
    chunker = SemanticChunker(max_token_threshold=80, min_token_threshold=10)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 3
    assert any("# 项目设计说明书" in c for c in chunks)
    assert any("# 附录 A" in c for c in chunks)

    _write_outputs("complex_markdown_long", chunks)


def test_mixed_numbering_long_chunking() -> None:
    text = _read("mixed_numbering_long.txt")
    chunker = SemanticChunker(max_token_threshold=60, min_token_threshold=5)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert any(c.lstrip().startswith("第一章") for c in chunks)
    assert any(c.lstrip().startswith("第二章") for c in chunks)

    _write_outputs("mixed_numbering_long", chunks)


def test_wall_of_text_long_fallback_chunking() -> None:
    text = _read("wall_of_text_long.txt")
    chunker = SemanticChunker(max_token_threshold=80, min_token_threshold=10)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert not any(c.lstrip().startswith("#") for c in chunks)

    _write_outputs("wall_of_text_long", chunks)


def run_tests() -> bool:
    print("\n" + "=" * 70)
    print("GraphRAG Chunker 测试套件")
    print("=" * 70)

    tests = [
        ("Markdown 结构化分块", test_markdown_semantic_chunking),
        ("中文大纲分块", test_chinese_outline_chunking),
        ("无结构回退分块", test_fallback_paragraphs_chunking),
        ("复杂 Markdown 长文", test_complex_markdown_long_chunking),
        ("混合编号长文", test_mixed_numbering_long_chunking),
        ("文本墙回退长文", test_wall_of_text_long_fallback_chunking),
    ]

    results: list[tuple[str, bool, str]] = []
    for i, (name, test_func) in enumerate(tests, 1):
        print("\n" + "=" * 70)
        print(f"【{i}/{len(tests)}】测试 {name}")
        print("=" * 70)
        try:
            test_func()
            results.append((name, True, ""))
            print(f"\n✅ {name} 测试通过")
        except Exception as e:
            results.append((name, False, repr(e)))
            print(f"\n❌ {name} 测试失败: {repr(e)}")
            traceback.print_exc()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    print(f"\n总测试数: {len(results)}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    if failed:
        print("\n失败的测试:")
        for name, ok, err in results:
            if not ok:
                print(f"  - {name}: {err}")

    print("\n" + "=" * 70)
    if failed == 0:
        print("✅ 所有测试通过！")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)
