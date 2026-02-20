"""运行所有 Data 模块测试"""

def run_all_tests():
    print("\n" + "=" * 70)
    print(" " * 20 + "GraphRAG Data 模块测试套件")
    print("=" * 70)

    results = {"passed": 0, "failed": 0, "errors": []}

    for i, (name, mod_run) in enumerate([
        ("Neo4jClient", "test_neo4j_client"),
        ("MilvusClient", "test_milvus_client"),
        ("PostgresClient", "test_postgres_client"),
        ("DataManager", "test_data_manager"),
    ], 1):
        print("\n" + "=" * 70)
        print(f"【{i}/4】测试 {name} 模块")
        print("=" * 70)
        try:
            module = __import__(mod_run, fromlist=["run_tests"])
            module.run_tests()
            results["passed"] += 1
            print(f"\n✅ {name} 测试通过")
        except Exception as e:
            results["failed"] += 1
            results["errors"].append((name, str(e)))
            print(f"\n❌ {name} 测试失败: {e}")

    print("\n" + "=" * 70)
    print(" " * 25 + "测试总结")
    print("=" * 70)
    print(f"\n总模块数: {results['passed'] + results['failed']}")
    print(f"✅ 通过: {results['passed']}")
    print(f"❌ 失败: {results['failed']}")
    if results["errors"]:
        for name, err in results["errors"]:
            print(f"  • {name}: {err}")
    print("\n" + "=" * 70)
    if results["failed"] == 0:
        print("🎉 所有测试通过！Data 模块工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    print("=" * 70 + "\n")
    return results["failed"] == 0
