"""运行所有配置模块测试"""

def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*70)
    print(" "*20 + "GraphRAG Config 模块测试套件")
    print("="*70)
    
    test_results = {
        "passed": 0,
        "failed": 0,
        "errors": []
    }
    
    # 测试 ConfigLoader
    print("\n" + "="*70)
    print("【1/3】测试 ConfigLoader 模块")
    print("="*70)
    try:
        from test_config_loader import run_tests as run_loader_tests
        run_loader_tests()
        test_results["passed"] += 1
        print("\n✅ ConfigLoader 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("ConfigLoader", str(e)))
        print(f"\n❌ ConfigLoader 测试失败: {e}")
    
    # 测试 Settings
    print("\n" + "="*70)
    print("【2/3】测试 Settings 模块")
    print("="*70)
    try:
        from test_settings import run_tests as run_settings_tests
        run_settings_tests()
        test_results["passed"] += 1
        print("\n✅ Settings 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("Settings", str(e)))
        print(f"\n❌ Settings 测试失败: {e}")
    
    # 测试 ConfigManager
    print("\n" + "="*70)
    print("【3/3】测试 ConfigManager 模块")
    print("="*70)
    try:
        from test_config_manager import run_tests as run_manager_tests
        run_manager_tests()
        test_results["passed"] += 1
        print("\n✅ ConfigManager 测试通过")
    except Exception as e:
        test_results["failed"] += 1
        test_results["errors"].append(("ConfigManager", str(e)))
        print(f"\n❌ ConfigManager 测试失败: {e}")
    
    # 打印总结
    print("\n" + "="*70)
    print(" "*25 + "测试总结")
    print("="*70)
    print(f"\n总测试模块数: {test_results['passed'] + test_results['failed']}")
    print(f"✅ 通过: {test_results['passed']}")
    print(f"❌ 失败: {test_results['failed']}")
    
    if test_results["errors"]:
        print("\n失败详情:")
        for module, error in test_results["errors"]:
            print(f"  • {module}: {error}")
    
    print("\n" + "="*70)
    
    if test_results["failed"] == 0:
        print("🎉 所有测试通过！配置模块工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    
    print("="*70 + "\n")
    
    return test_results["failed"] == 0
