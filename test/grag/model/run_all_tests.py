"""运行所有 Model 模块测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print(" " * 20 + "GraphRAG Model 模块测试套件")
    print("=" * 70)

    test_results = {
        "passed": 0,
        "failed": 0,
        "errors": [],
    }

    # 1. 测试 LLMClient
    print("\n" + "=" * 70)
    print("【1/4】测试 LLMClient 模块")
    print("=" * 70)
    try:
        from test_llm_client import run_tests as run_llm_tests
        run_llm_tests()
        test_results["passed"] += 1
        print("\n✅ LLMClient 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("LLMClient", str(e)))
        print(f"\n❌ LLMClient 测试失败: {e}")

    # 2. 测试 EmbeddingClient
    print("\n" + "=" * 70)
    print("【2/4】测试 EmbeddingClient 模块")
    print("=" * 70)
    try:
        from test_embedding_client import run_tests as run_embedding_tests
        run_embedding_tests()
        test_results["passed"] += 1
        print("\n✅ EmbeddingClient 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("EmbeddingClient", str(e)))
        print(f"\n❌ EmbeddingClient 测试失败: {e}")

    # 3. 测试 RerankerClient
    print("\n" + "=" * 70)
    print("【3/4】测试 RerankerClient 模块")
    print("=" * 70)
    try:
        from test_reranker_client import run_tests as run_reranker_tests
        run_reranker_tests()
        test_results["passed"] += 1
        print("\n✅ RerankerClient 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("RerankerClient", str(e)))
        print(f"\n❌ RerankerClient 测试失败: {e}")

    # 4. 测试 ModelManager
    print("\n" + "=" * 70)
    print("【4/4】测试 ModelManager 模块")
    print("=" * 70)
    try:
        from test_model_manager import run_tests as run_manager_tests
        run_manager_tests()
        test_results["passed"] += 1
        print("\n✅ ModelManager 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("ModelManager", str(e)))
        print(f"\n❌ ModelManager 测试失败: {e}")

    # 打印总结
    print("\n" + "=" * 70)
    print(" " * 25 + "测试总结")
    print("=" * 70)
    print(f"\n总测试模块数: {test_results['passed'] + test_results['failed']}")
    print(f"✅ 通过: {test_results['passed']}")
    print(f"❌ 失败: {test_results['failed']}")

    if test_results["errors"]:
        print("\n失败详情:")
        for module, error in test_results["errors"]:
            print(f"  • {module}: {error}")

    print("\n" + "=" * 70)

    if test_results["failed"] == 0:
        print("🎉 所有测试通过！Model 模块工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")

    print("=" * 70 + "\n")

    return test_results["failed"] == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
