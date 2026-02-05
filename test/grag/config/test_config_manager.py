"""测试配置管理器 (ConfigManager)"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.config.config_manager import (
    ConfigManager,
    get_config_manager,
    initialize_config,
    get_grag_config,
    get_grag_settings
)
from grag.config.settings import ProviderType


class TestConfigManager:
    """测试 ConfigManager 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        self.manager = ConfigManager()

    def test_initialize(self):
        """测试初始化配置管理器"""
        print("\n=== 测试初始化配置管理器 ===")
        
        success = self.manager.initialize()
        
        assert success, "配置初始化应该成功"
        print("✅ 配置管理器初始化成功")

    def test_get_config(self):
        """测试获取配置字典"""
        print("\n=== 测试获取配置字典 ===")
        
        self.manager.initialize()
        config = self.manager.get_config()
        
        assert config is not None, "配置不应为空"
        assert isinstance(config, dict), "配置应该是字典类型"
        assert "llm_provider" in config, "应包含 llm_provider"
        
        print(f"✅ 获取配置成功，包含 {len(config)} 个顶层键")

    def test_get_settings(self):
        """测试获取设置对象"""
        print("\n=== 测试获取设置对象 ===")
        
        self.manager.initialize()
        settings = self.manager.get_settings()
        
        assert settings is not None, "设置对象不应为空"
        assert hasattr(settings, 'llm_provider'), "应有 llm_provider 属性"
        
        print(f"✅ 获取设置对象成功")
        print(f"   LLM 提供商: {settings.llm_provider}")
        print(f"   向量数据库: {settings.vector_db_provider}")
        print(f"   图数据库: {settings.graph_db_provider}")

    def test_get_config_value(self):
        """测试获取配置值"""
        print("\n=== 测试获取配置值 ===")
        
        self.manager.initialize()
        
        # 获取简单值
        llm_provider = self.manager.get_config_value("llm_provider")
        assert llm_provider is not None, "应该能获取到 LLM 提供商"
        print(f"✅ LLM 提供商: {llm_provider}")
        
        # 获取嵌套值
        model = self.manager.get_config_value("llm_providers.siliconflow.model")
        assert model is not None, "应该能获取到模型名称"
        print(f"✅ 模型名称: {model}")

    def test_set_config_value(self):
        """测试设置配置值"""
        print("\n=== 测试设置配置值 ===")
        
        self.manager.initialize()
        
        # 设置新值
        self.manager.set_config_value("llm_providers.siliconflow.temperature", 0.8)
        
        # 验证设置成功
        new_temp = self.manager.get_config_value("llm_providers.siliconflow.temperature")
        assert new_temp == 0.8, "设置的值应该生效"
        print(f"✅ 成功设置温度参数: {new_temp}")

    def test_get_provider_config(self):
        """测试获取提供商配置"""
        print("\n=== 测试获取提供商配置 ===")
        
        self.manager.initialize()
        
        # 获取默认 LLM 提供商配置
        llm_config = self.manager.get_provider_config(ProviderType.LLM)
        assert llm_config is not None, "应该能获取到 LLM 配置"
        assert hasattr(llm_config, 'model'), "LLM 配置应有 model 属性"
        print(f"✅ 默认 LLM 配置: {llm_config.model}")
        
        # 获取指定的向量数据库配置
        milvus_config = self.manager.get_provider_config(
            ProviderType.VECTOR_DB,
            "milvus"
        )
        assert milvus_config is not None, "应该能获取到 Milvus 配置"
        print(f"✅ Milvus 配置: host={milvus_config.host}, port={milvus_config.port}")

    def test_validation_results(self):
        """测试验证结果"""
        print("\n=== 测试验证结果 ===")
        
        self.manager.initialize()
        
        results = self.manager.get_validation_results()
        assert isinstance(results, list), "验证结果应该是列表"
        
        has_errors = self.manager.has_errors()
        has_warnings = self.manager.has_warnings()
        
        print(f"✅ 验证结果数量: {len(results)}")
        print(f"   存在错误: {has_errors}")
        print(f"   存在警告: {has_warnings}")

    def test_config_info(self):
        """测试获取配置信息"""
        print("\n=== 测试获取配置信息 ===")
        
        self.manager.initialize()
        
        info = self.manager.get_config_info()
        
        assert "initialized" in info, "应包含初始化状态"
        assert info["initialized"] is True, "应该已初始化"
        
        print(f"✅ 配置信息:")
        print(f"   已初始化: {info['initialized']}")
        print(f"   存在错误: {info['has_errors']}")
        print(f"   存在警告: {info['has_warnings']}")
        print(f"   LLM 提供商: {info.get('llm_provider')}")


class TestGlobalFunctions:
    """测试全局函数"""

    def test_initialize_config(self):
        """测试全局初始化函数"""
        print("\n=== 测试全局初始化函数 ===")
        
        success = initialize_config()
        assert success, "全局初始化应该成功"
        print("✅ 全局初始化成功")

    def test_get_grag_config(self):
        """测试获取全局配置"""
        print("\n=== 测试获取全局配置 ===")
        
        initialize_config()
        config = get_grag_config()
        
        assert config is not None, "配置不应为空"
        assert "llm_provider" in config, "应包含 llm_provider"
        print(f"✅ 获取全局配置成功")

    def test_get_grag_settings(self):
        """测试获取全局设置"""
        print("\n=== 测试获取全局设置 ===")
        
        initialize_config()
        settings = get_grag_settings()
        
        assert settings is not None, "设置不应为空"
        assert hasattr(settings, 'llm_provider'), "应有 llm_provider 属性"
        print(f"✅ 获取全局设置成功")
        print(f"   LLM 提供商: {settings.llm_provider}")


class TestDatabaseConfigs:
    """测试数据库配置"""

    def setup_method(self):
        """每个测试方法前执行"""
        self.manager = ConfigManager()
        self.manager.initialize()

    def test_neo4j_config(self):
        """测试 Neo4j 配置"""
        print("\n=== 测试 Neo4j 配置 ===")
        
        neo4j_config = self.manager.get_provider_config(
            ProviderType.GRAPH_DB,
            "neo4j"
        )
        
        assert neo4j_config is not None, "Neo4j 配置不应为空"
        assert neo4j_config.uri is not None, "应有 URI"
        assert neo4j_config.user == "neo4j", "用户名应为 neo4j"
        
        print(f"✅ Neo4j 配置:")
        print(f"   URI: {neo4j_config.uri}")
        print(f"   用户: {neo4j_config.user}")
        print(f"   数据库: {neo4j_config.database}")

    def test_milvus_config(self):
        """测试 Milvus 配置"""
        print("\n=== 测试 Milvus 配置 ===")
        
        milvus_config = self.manager.get_provider_config(
            ProviderType.VECTOR_DB,
            "milvus"
        )
        
        assert milvus_config is not None, "Milvus 配置不应为空"
        assert milvus_config.host == "localhost", "主机应为 localhost"
        assert milvus_config.port == 19530, "端口应为 19530"
        
        print(f"✅ Milvus 配置:")
        print(f"   主机: {milvus_config.host}")
        print(f"   端口: {milvus_config.port}")
        print(f"   集合: {milvus_config.collection_name}")

    def test_postgres_config(self):
        """测试 PostgreSQL 配置"""
        print("\n=== 测试 PostgreSQL 配置 ===")
        
        postgres_config = self.manager.get_provider_config(
            ProviderType.RELATIONAL_DB,
            "postgres"
        )
        
        assert postgres_config is not None, "PostgreSQL 配置不应为空"
        assert postgres_config.host == "localhost", "主机应为 localhost"
        assert postgres_config.port == 5430, "端口应为 5430"
        assert postgres_config.database == "grag", "数据库应为 grag"
        
        print(f"✅ PostgreSQL 配置:")
        print(f"   主机: {postgres_config.host}")
        print(f"   端口: {postgres_config.port}")
        print(f"   数据库: {postgres_config.database}")
        print(f"   用户: {postgres_config.user}")


def run_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("开始测试 ConfigManager 模块")
    print("="*60)
    
    # 创建测试实例
    test_manager = TestConfigManager()
    test_global = TestGlobalFunctions()
    test_db = TestDatabaseConfigs()
    
    try:
        # 测试 ConfigManager 类
        test_manager.setup_method()
        test_manager.test_initialize()
        
        test_manager.setup_method()
        test_manager.test_get_config()
        
        test_manager.setup_method()
        test_manager.test_get_settings()
        
        test_manager.setup_method()
        test_manager.test_get_config_value()
        
        test_manager.setup_method()
        test_manager.test_set_config_value()
        
        test_manager.setup_method()
        test_manager.test_get_provider_config()
        
        test_manager.setup_method()
        test_manager.test_validation_results()
        
        test_manager.setup_method()
        test_manager.test_config_info()
        
        # 测试全局函数
        test_global.test_initialize_config()
        test_global.test_get_grag_config()
        test_global.test_get_grag_settings()
        
        # 测试数据库配置
        test_db.setup_method()
        test_db.test_neo4j_config()
        
        test_db.setup_method()
        test_db.test_milvus_config()
        
        test_db.setup_method()
        test_db.test_postgres_config()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        raise
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    run_tests()
