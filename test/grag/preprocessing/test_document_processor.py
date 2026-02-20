"""测试文档处理器

测试各种文档格式的读取和处理功能
"""

from pathlib import Path

import pytest

from grag.preprocessing import get_document_processor
from grag.config import initialize_config, get_grag_settings, ProviderType


def test_document_processor():
    """测试文档处理器基本功能"""
    print("\n" + "=" * 70)
    print("测试文档处理器")
    print("=" * 70)
    
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
    assert isinstance(formats, list)
    assert len(formats) > 0
    print(f"支持的格式: {', '.join(formats)}")

    # 视觉模型配置可能依赖 openai 等可选依赖；缺失时跳过校验。
    try:
        print("\n=== 视觉模型配置 ===")
        vision_info = processor._get_vision_client().get_config_info()
        settings = get_grag_settings()
        vision_cfg = settings.get_provider_config(ProviderType.VISION)
        assert vision_info["provider"] == settings.vision_provider
        assert vision_info["model"] == vision_cfg.model
        assert vision_info["base_url"] == vision_cfg.base_url
    except ImportError as e:
        pytest.skip(f"vision client optional dependency missing: {e}")

    # LLMClient 仅做配置一致性校验（不触发真实请求）
    print("\n=== LLM配置 ===")
    llm_client = processor._get_llm_client()
    llm_info = llm_client.get_provider_info()
    settings = get_grag_settings()
    llm_cfg = settings.get_provider_config(ProviderType.LLM)
    assert llm_info["provider_name"] == settings.llm_provider
    assert llm_info["model"] == llm_cfg.model
    assert llm_info["base_url"] == llm_cfg.base_url


def test_process_single_file(tmp_path: Path) -> None:
    """测试处理单个文件（使用 pytest tmp_path 自动创建输入文件）。"""

    initialize_config()
    processor = get_document_processor()

    input_file = tmp_path / "input.txt"
    input_file.write_text("第一行\n第二行", encoding="utf-8")

    content = processor.process_file(input_file, standardize=False)
    assert "第一行" in content
    assert "第二行" in content


def test_batch_process(tmp_path: Path) -> None:
    """测试 batch_process（使用 pytest tmp_path 自动准备输入目录）。"""

    initialize_config()
    processor = get_document_processor()

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / "a.txt").write_text("a", encoding="utf-8")
    (input_dir / "b.txt").write_text("b", encoding="utf-8")

    results = processor.batch_process(
        input_dir=input_dir,
        output_dir=output_dir,
        standardize=False,
        recursive=False,
    )
    assert results["total"] == 2
    assert results["success"] == 2
    assert results["failed"] == 0
    assert (output_dir / "a.txt").exists()
    assert (output_dir / "b.txt").exists()
