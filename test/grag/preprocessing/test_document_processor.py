"""测试文档处理器

测试各种文档格式的读取和处理功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.preprocessing import get_document_processor
from grag.config import initialize_config, get_grag_settings, ProviderType


def test_document_processor():
    """测试文档处理器基本功能"""
    print("\n" + "=" * 70)
    print("测试文档处理器")
    print("=" * 70)
    
    try:
        # 初始化配置
        print("\n=== 初始化配置 ===")
        initialize_config()
        print("✅ 配置初始化成功")
        
        # 创建文档处理器
        print("\n=== 创建文档处理器 ===")
        processor = get_document_processor()
        print("✅ 文档处理器创建成功")
        
        # 显示支持的格式
        print("\n=== 支持的文件格式 ===")
        formats = processor.get_supported_formats()
        print(f"支持的格式: {', '.join(formats)}")
        
        # 显示配置信息
        print("\n=== 视觉模型配置 ===")
        vision_info = processor._get_vision_client().get_config_info()
        print(f"提供商: {vision_info['provider']}")
        print(f"模型: {vision_info['model']}")
        print(f"API地址: {vision_info['base_url']}")
        
        print("\n=== LLM配置 ===")
        llm_client = processor._get_llm_client()
        # LLMClient 提供 get_provider_info，用于查看当前使用的模型配置
        llm_info = llm_client.get_provider_info()
        print(f"提供商: {llm_info['provider_name']}")
        print(f"模型: {llm_info['model']}")
        print(f"API地址: {llm_info['base_url']}")

        # 校验视觉模型与 LLM 的配置与 grag_config.yaml / GraphRAGSettings 一致
        settings = get_grag_settings()

        # 视觉模型配置校验
        vision_cfg = settings.get_provider_config(ProviderType.VISION)
        assert vision_info["provider"] == settings.vision_provider, "视觉模型提供商应与配置一致"
        assert vision_info["model"] == vision_cfg.model, "视觉模型名称应与配置一致"
        assert vision_info["base_url"] == vision_cfg.base_url, "视觉模型 base_url 应与配置一致"

        # LLM 配置校验
        llm_cfg = settings.get_provider_config(ProviderType.LLM)
        assert llm_info["provider_name"] == settings.llm_provider, "LLM 提供商应与配置一致"
        assert llm_info["model"] == llm_cfg.model, "LLM 模型名称应与配置一致"
        assert llm_info["base_url"] == llm_cfg.base_url, "LLM base_url 应与配置一致"
        
        print("\n" + "=" * 70)
        print("✅ 文档处理器测试通过")
        print("=" * 70)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_process_single_file():
    """测试处理单个文件"""
    print("\n" + "=" * 70)
    print("测试处理单个文件")
    print("=" * 70)
    
    try:
        initialize_config()
        processor = get_document_processor()
        
        input_dir = Path(project_root) / "test"  / "grag" / "preprocessing" / "test_data" / "input"
        output_dir = Path(project_root) / "test"  / "grag" / "preprocessing" / "test_data" / "output"
        
        print(f"\n输入目录: {input_dir}")
        print(f"输出目录: {output_dir}")
        
        # 检查输入目录中的文件
        if not input_dir.exists():
            print(f"\n⚠️  输入目录不存在，创建目录: {input_dir}")
            input_dir.mkdir(parents=True, exist_ok=True)
        
        files = list(input_dir.iterdir())
        if not files:
            print("\n⚠️  输入目录为空，请将测试文件放入以下目录:")
            print(f"   {input_dir}")
            print("\n支持的文件格式:")
            for fmt in processor.get_supported_formats():
                print(f"   - {fmt}")
            return True
        
        print(f"\n找到 {len(files)} 个文件:")
        for f in files:
            print(f"  - {f.name}")
        
        # 处理每个文件
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path in files:
            if file_path.is_file():
                print(f"\n--- 处理文件: {file_path.name} ---")
                
                try:
                    # 处理文件
                    content = processor.process_file(file_path, standardize=True)
                    
                    # 保存结果
                    output_file = output_dir / f"{file_path.stem}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    print(f"✅ 成功处理，输出到: {output_file}")
                    print(f"   内容长度: {len(content)} 字符")
                    print(f"   预览: {content[:200]}...")
                    
                except Exception as e:
                    print(f"❌ 处理失败: {e}")
        
        print("\n" + "=" * 70)
        print("✅ 单文件处理测试完成")
        print("=" * 70)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_batch_process():
    """测试批量处理"""
    print("\n" + "=" * 70)
    print("测试批量处理文档")
    print("=" * 70)
    
    try:
        initialize_config()
        processor = get_document_processor()
        
        input_dir = Path(project_root) / "test"  / "grag" / "preprocessing" / "test_data" / "input"
        output_dir = Path(project_root) / "test"  / "grag" / "preprocessing" / "test_data" / "output"
        
        print(f"\n输入目录: {input_dir}")
        print(f"输出目录: {output_dir}")
        
        # 确保目录存在
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 批量处理
        print("\n=== 开始批量处理 ===")
        results = processor.batch_process(
            input_dir=input_dir,
            output_dir=output_dir,
            standardize=True,
            recursive=False
        )
        
        # 显示结果
        print("\n=== 处理结果 ===")
        print(f"总文件数: {results['total']}")
        print(f"成功: {results['success']}")
        print(f"失败: {results['failed']}")
        
        if results['errors']:
            print("\n错误详情:")
            for error in results['errors']:
                print(f"  ❌ {error}")
        
        if results['total'] == 0:
            print("\n⚠️  没有找到文件，请将测试文件放入输入目录")
            print(f"   输入目录: {input_dir}")
        elif results['success'] > 0:
            print(f"\n✅ 成功处理 {results['success']} 个文件")
            print(f"   输出目录: {output_dir}")
        
        print("\n" + "=" * 70)
        print("✅ 批量处理测试完成")
        print("=" * 70)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("GraphRAG 文档处理器测试套件")
    print("=" * 70)
    
    tests = [
        ("文档处理器基本功能", test_document_processor),
        ("单文件处理", test_process_single_file),
        ("批量处理", test_batch_process),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n{'=' * 70}")
        print(f"【{len(results) + 1}/{len(tests)}】测试 {name}")
        print(f"{'=' * 70}")
        
        success = test_func()
        results.append((name, success))
    
    # 打印总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    
    passed = sum(1 for _, success in results if success)
    failed = len(results) - passed
    
    print(f"\n总测试数: {len(results)}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    
    if failed > 0:
        print("\n失败的测试:")
        for name, success in results:
            if not success:
                print(f"  • {name}")
    
    print("\n" + "=" * 70)
    if failed == 0:
        print("🎉 所有测试通过！文档处理器工作正常。")
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    exit(0 if ok else 1)
