"""测试配置加载器 (ConfigLoader)"""

import os
import pytest

from grag.config.config_loader import ConfigLoader, load_grag_config, get_config_value


class TestConfigLoader:
    """测试 ConfigLoader 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        self.loader = ConfigLoader()

    def test_load_grag_config(self):
        """测试加载 grag_config.yaml"""
        print("\n=== 测试加载 grag_config.yaml ===")
        
        config = self.loader.load_config("grag_config.yaml")
        
        # 验证配置不为空
        assert config is not None, "配置不应为空"
        assert isinstance(config, dict), "配置应该是字典类型"
        
        # 验证必需的顶层键
        required_keys = [
            "llm_provider",
            "embedding_provider",
            "vector_db_provider",
            "graph_db_provider",
            "relational_db_provider",
            "llm_providers",
            "embedding_providers",
            "vector_databases",
            "graph_databases",
            "relational_databases"
        ]
        
        for key in required_keys:
            assert key in config, f"配置中应包含 '{key}' 键"
        
        print(f"✅ 配置加载成功，包含 {len(config)} 个顶层键")
        print(f"   默认 LLM 提供商: {config.get('llm_provider')}")
        print(f"   默认向量数据库: {config.get('vector_db_provider')}")
        print(f"   默认图数据库: {config.get('graph_db_provider')}")

    def test_get_config_value(self):
        """测试获取嵌套配置值"""
        print("\n=== 测试获取嵌套配置值 ===")
        
        config = self.loader.load_config("grag_config.yaml")
        
        # 测试获取嵌套值
        llm_model = self.loader.get_config_value(
            config, 
            "llm_providers.siliconflow.model"
        )
        assert llm_model is not None, "应该能获取到 LLM 模型名称"
        print(f"✅ LLM 模型: {llm_model}")
        
        # 测试获取向量数据库配置
        milvus_host = self.loader.get_config_value(
            config,
            "vector_databases.milvus.host"
        )
        assert milvus_host is not None, "应该能获取到 Milvus 主机地址"
        print(f"✅ Milvus 主机: {milvus_host}")
        
        # 测试获取不存在的键（使用默认值）
        non_existent = self.loader.get_config_value(
            config,
            "non.existent.key",
            default="default_value"
        )
        assert non_existent == "default_value", "不存在的键应返回默认值"
        print(f"✅ 不存在的键返回默认值: {non_existent}")

    def test_set_config_value(self):
        """测试设置配置值"""
        print("\n=== 测试设置配置值 ===")
        
        config = self.loader.load_config("grag_config.yaml")
        
        # 设置新值
        self.loader.set_config_value(
            config,
            "llm_providers.siliconflow.temperature",
            0.5
        )
        
        # 验证设置成功
        new_temp = self.loader.get_config_value(
            config,
            "llm_providers.siliconflow.temperature"
        )
        assert new_temp == 0.5, "设置的值应该生效"
        print(f"✅ 成功设置温度参数: {new_temp}")

    def test_env_var_interpolation(self):
        """测试环境变量插值"""
        print("\n=== 测试环境变量插值 ===")
        
        # 设置测试环境变量
        os.environ["TEST_API_KEY"] = "test_key_12345"
        
        # 创建测试配置
        test_config = {
            "api_key": "${TEST_API_KEY}",
            "url": "${TEST_URL:https://default.com}"
        }
        
        # 处理环境变量
        processed = self.loader._process_env_vars(test_config)
        
        assert processed["api_key"] == "test_key_12345", "应该替换环境变量"
        assert processed["url"] == "https://default.com", "应该使用默认值"
        
        print(f"✅ 环境变量替换: {processed['api_key']}")
        print(f"✅ 默认值使用: {processed['url']}")
        
        # 清理
        del os.environ["TEST_API_KEY"]

    def test_config_cache(self):
        """测试配置缓存"""
        print("\n=== 测试配置缓存 ===")
        
        # 第一次加载
        config1 = self.loader.load_config("grag_config.yaml")
        
        # 第二次加载（应该使用缓存）
        config2 = self.loader.load_config("grag_config.yaml")
        
        # 验证是同一个对象（缓存生效）
        assert config1 is config2, "第二次加载应该使用缓存"
        print("✅ 配置缓存生效")
        
        # 强制重新加载
        config3 = self.loader.load_config("grag_config.yaml", force_reload=True)
        assert config3 is not config2, "强制重新加载应该返回新对象"
        print("✅ 强制重新加载成功")

    def test_cache_info(self):
        """测试获取缓存信息"""
        print("\n=== 测试缓存信息 ===")
        
        # 加载配置
        self.loader.load_config("grag_config.yaml")
        
        # 获取缓存信息
        cache_info = self.loader.get_cache_info()
        
        assert "cached_configs" in cache_info, "应包含缓存配置列表"
        assert "grag_config.yaml" in cache_info["cached_configs"], "应包含已加载的配置"
        
        print(f"✅ 缓存的配置: {cache_info['cached_configs']}")
        print(f"✅ 缓存详情: {cache_info['cache_info']}")


class TestGlobalFunctions:
    """测试全局函数"""

    def test_load_grag_config_function(self):
        """测试全局 load_grag_config 函数"""
        print("\n=== 测试全局 load_grag_config 函数 ===")
        
        config = load_grag_config()
        
        assert config is not None, "配置不应为空"
        assert "llm_provider" in config, "应包含 llm_provider"
        
        print(f"✅ 全局函数加载成功")
        print(f"   LLM 提供商: {config['llm_provider']}")

    def test_get_config_value_function(self):
        """测试全局 get_config_value 函数"""
        print("\n=== 测试全局 get_config_value 函数 ===")
        
        # 获取配置值
        llm_provider = get_config_value("llm_provider")
        assert llm_provider is not None, "应该能获取到 LLM 提供商"
        print(f"✅ LLM 提供商: {llm_provider}")
        
        # 获取嵌套值
        model = get_config_value("llm_providers.siliconflow.model")
        assert model is not None, "应该能获取到模型名称"
        print(f"✅ 模型名称: {model}")
