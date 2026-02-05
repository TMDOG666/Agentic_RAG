"""运行所有预处理模块测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def run_all_tests():
    """运行所有预处理相关测试"""
    print("\n" + "=" * 70)
    print(" " * 20 + "GraphRAG Preprocessing 模块测试套件")
    print("=" * 70)

    results = {"passed": 0, "failed": 0, "errors": []}

    # 1. 文档处理器
    print("\n" + "=" * 70)
    print("【1/3】测试 DocumentProcessor 模块")
    print("=" * 70)
    try:
        from test_document_processor import run_tests as run_doc_tests
        ok = run_doc_tests()
        if ok:
            results["passed"] += 1
            print("\n✅ DocumentProcessor 测试通过")
        else:
            results["failed"] += 1
            results["errors"].append(("DocumentProcessor", "用例返回失败"))
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(("DocumentProcessor", str(e)))
        print(f"\n❌ DocumentProcessor 测试异常: {e}")

    # 2. TextCleaner
    print("\n" + "=" * 70)
    print("【2/3】测试 TextCleaner 模块")
    print("=" * 70)
    try:
        from test_text_cleaner import run_tests as run_cleaner_tests
        ok = run_cleaner_tests()
        if ok:
            results["passed"] += 1
            print("\n✅ TextCleaner 测试通过")
        else:
            results["failed"] += 1
            results["errors"].append(("TextCleaner", "用例返回失败"))
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(("TextCleaner", str(e)))
        print(f"\n❌ TextCleaner 测试异常: {e}")

    # 3. PreprocessingManager
    print("\n" + "=" * 70)
    print("【3/3】测试 PreprocessingManager 模块")
    print("=" * 70)
    try:
        from test_preprocessing_manager import run_tests as run_mgr_tests
        ok = run_mgr_tests()
        if ok:
            results["passed"] += 1
            print("\n✅ PreprocessingManager 测试通过")
        else:
            results["failed"] += 1
            results["errors"].append(("PreprocessingManager", "用例返回失败"))
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(("PreprocessingManager", str(e)))
        print(f"\n❌ PreprocessingManager 测试异常: {e}")

    # 总结
    print("\n" + "=" * 70)
    print(" " * 25 + "测试总结")
    print("=" * 70)
    total = results["passed"] + results["failed"]
    print(f"\n总测试模块数: {total}")
    print(f"✅ 通过: {results['passed']}")
    print(f"❌ 失败: {results['failed']}")

    if results["errors"]:
        print("\n失败详情:")
        for name, err in results["errors"]:
            print(f"  • {name}: {err}")

    print("\n" + "=" * 70)
    if results["failed"] == 0:
        print("🎉 所有测试通过！Preprocessing 模块工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    print("=" * 70 + "\n")

    return results["failed"] == 0


if __name__ == "__main__":
    ok = run_all_tests()
    sys.exit(0 if ok else 1)

