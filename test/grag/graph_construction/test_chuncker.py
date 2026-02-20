from pathlib import Path

import json

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
    if p.exists():
        return p.read_text(encoding="utf-8")

    # 自包含样例：当仓库未提供 test_data/input 时（例如 CI / 新环境），使用内置文本。
    samples: dict[str, str] = {
        "markdown_semantic.md": """# 第一章 标题A\n\n这里是第一章内容。\n\n# 第二章 标题B\n\n这里是第二章内容。\n""",
        "chinese_outline.txt": """第一章 概述\n这里是第一章内容。\n\n第二章 细节\n这里是第二章内容。\n""",
        "fallback_paragraphs.txt": """没有任何标题\n\n这是第一段。\n\n这是第二段。\n""",
        "complex_markdown_long.txt": """# 项目设计说明书\n\n## 背景\n这里是背景内容。\n\n## 目标\n这里是目标内容。\n\n# 附录 A\n\n这里是附录内容。\n""",
        "mixed_numbering_long.txt": """第一章 章节一\n这里是第一章内容。\n\n1.1 小节\n这里是小节内容。\n\n第二章 章节二\n这里是第二章内容。\n""",
        "wall_of_text_long.txt": """这是一段没有标题的长文本。为了触发回退分块，我们准备多段内容。\n\n第二段开始。这里继续写一些文字。\n\n第三段继续。这里再写一些文字。\n""",
    }
    return samples.get(name, "")


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
    assert any("第一章" in c for c in chunks)
    assert any("第二章" in c for c in chunks)

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
    assert any("第一章" in c for c in chunks)
    assert any("第二章" in c for c in chunks)

    _write_outputs("mixed_numbering_long", chunks)


def test_wall_of_text_long_fallback_chunking() -> None:
    text = _read("wall_of_text_long.txt")
    chunker = SemanticChunker(max_token_threshold=80, min_token_threshold=10)
    chunks = chunker.chunk(text)

    assert len(chunks) >= 2
    assert not any(c.lstrip().startswith("#") for c in chunks)

    _write_outputs("wall_of_text_long", chunks)
