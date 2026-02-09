import sys
from pathlib import Path

import asyncio
import json
import traceback

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.coreference_resolver import CoreferenceResolver


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.coreference.json").write_text(content, encoding="utf-8")


def test_coreference_replace_row_with_result() -> None:
    """验证：LLM 返回的 JSON 列表能正确驱动“row -> result”的替换。

    这里用 fake LLM：直接返回 JSON 字符串，避免真实请求外部大模型。
    """

    def fake_llm_chat(_prompt: str) -> str:
        # 返回严格的 JSON 列表，符合 coreference_resolver.py 的 prompt 约束。
        return json.dumps(
            [
                {"raw": "他看起来很疲惫", "result": "警长看起来很疲惫"},
                {"raw": "这是你干的", "result": "这是嫌疑人干的"},
            ],
            ensure_ascii=False,
        )

    resolver = CoreferenceResolver(llm_chat_fn=fake_llm_chat)

    # 收敛重试等待时间，避免单测太慢。
    resolver.base_sleep_seconds = 0.01
    resolver.max_retries = 2

    text = "警长推开了审讯室的门。他看起来很疲惫。警长把一份文件扔在桌上，问道：这是你干的吗？"
    result = asyncio.run(resolver.resolve_text(text))

    # 断言：成功返回、解析到 raw，并且 resolved_text 中出现替换后的内容。
    assert result.error is None
    assert result.coreference_raw
    assert "警长看起来很疲惫" in result.resolved_text
    assert "这是嫌疑人干的" in result.resolved_text

    _write_outputs(
        "replace_row_with_result",
        {
            "text": result.text,
            "coreference_raw": result.coreference_raw,
            "resolved_text": result.resolved_text,
            "error": result.error,
        },
    )


def test_coreference_invalid_json_should_return_error() -> None:
    """验证：LLM 输出非法 JSON 时，能返回错误并回退到原文。

    这保证指代消解失败不会阻断后续实体关系抽取。
    """

    def fake_llm_chat(_prompt: str) -> str:
        return "not a json"

    resolver = CoreferenceResolver(llm_chat_fn=fake_llm_chat)

    # 这里不需要重试，直接让它失败并返回 error。
    resolver.base_sleep_seconds = 0.01
    resolver.max_retries = 1

    text = "他看起来很疲惫。"
    result = asyncio.run(resolver.resolve_text(text))

    # 断言：出现错误，resolved_text 保持原始输入文本。
    assert result.error is not None
    assert result.resolved_text == text

    _write_outputs(
        "invalid_json",
        {
            "text": result.text,
            "coreference_raw": result.coreference_raw,
            "resolved_text": result.resolved_text,
            "error": result.error,
        },
    )


def run_tests() -> bool:
    print("\n" + "=" * 70)
    print("GraphRAG CoreferenceResolver 测试套件")
    print("=" * 70)

    tests = [
        ("替换 row -> result", test_coreference_replace_row_with_result),
        ("非法 JSON 回退", test_coreference_invalid_json_should_return_error),
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
