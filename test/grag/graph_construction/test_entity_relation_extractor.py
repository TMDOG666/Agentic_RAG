import sys
from pathlib import Path

import asyncio
import json
import time
import traceback

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.entity_relation_extractor import (
    Chunk,
    EntityRelationExtractor,
)


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    input_dir = base / "input"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.entity_relation.json").write_text(content, encoding="utf-8")


def test_async_concurrency_and_retry() -> None:
    started_at = time.time()

    calls: dict[str, int] = {}

    def fake_llm_chat(prompt: str) -> str:
        # 用 prompt 中的 chunk_id 标记来决定行为（简单起见从 prompt 里找不到就走默认）
        # 这里通过调用计数模拟“第一次失败，第二次成功”。
        key = "default"
        if "chunk_0" in prompt:
            key = "chunk_0"
        if "chunk_1" in prompt:
            key = "chunk_1"

        calls[key] = calls.get(key, 0) + 1
        if key == "chunk_1" and calls[key] == 1:
            raise RuntimeError("simulated transient error")

        return "\n".join(
            [
                "entity<|SEP|>测试实体<|SEP|>概念<|SEP|>用于单测",
                "relation<|SEP|>测试实体<|SEP|>测试实体<|SEP|>自环关系<|SEP|>测试<|SEP|>5",
                "<|DONE|>",
            ]
        )

    extractor = EntityRelationExtractor(llm_chat_fn=fake_llm_chat)

    # 强行收敛重试等待时间，避免单测太慢
    extractor.base_sleep_seconds = 0.01
    extractor.max_retries = 2

    chunks = [
        Chunk(chunk_id="chunk_0", text="故事第一部分..."),
        Chunk(chunk_id="chunk_1", text="故事第二部分..."),
    ]

    results = asyncio.run(extractor.extract_many(chunks))

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0].chunk_id == "chunk_0"
    assert results[1].chunk_id == "chunk_1"
    assert results[0].entity_relation_raw
    assert results[1].entity_relation_raw
    assert results[0].error is None
    assert results[1].error is None

    # chunk_1 应该触发一次失败后重试成功
    assert calls.get("chunk_1", 0) == 2

    _write_outputs(
        "async_concurrency_and_retry",
        {
            "elapsed_seconds": round(time.time() - started_at, 4),
            "results": [r.__dict__ for r in results],
            "calls": calls,
        },
    )


def run_tests() -> bool:
    print("\n" + "=" * 70)
    print("GraphRAG EntityRelationExtractor 测试套件")
    print("=" * 70)

    tests = [
        ("异步并发 + 重试", test_async_concurrency_and_retry),
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

    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)
