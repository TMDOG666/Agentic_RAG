"""测试 LLM 客户端 (LLMClient)"""

import os

from grag.config import get_config_manager
from grag.model.llm_client import (
    LLMClient,
    get_llm_client,
    get_llm_model,
)


def _ensure_config():
    """确保配置已初始化"""
    get_config_manager().initialize()


class TestLLMClient:
    """测试 LLMClient 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        _ensure_config()
        self.client = LLMClient()

    def test_llm_client_init(self):
        """测试 LLM 客户端初始化"""
        print("\n=== 测试 LLM 客户端初始化 ===")

        assert self.client is not None, "客户端不应为空"
        assert self.client._settings is not None, "配置不应为空"
        assert self.client.provider_name is None or isinstance(
            self.client.provider_name, str
        ), "提供商名称应为 None 或字符串"

        print("✅ LLM 客户端初始化成功")

    def test_llm_client_with_provider(self):
        """测试指定提供商的 LLM 客户端"""
        print("\n=== 测试指定提供商的 LLM 客户端 ===")

        client = LLMClient(provider_name="siliconflow")
        assert client.provider_name == "siliconflow", "提供商名称应正确设置"

        info = client.get_provider_info()
        assert info["provider_name"] == "siliconflow", "提供商信息应一致"
        assert "model" in info, "应包含 model"
        assert "base_url" in info, "应包含 base_url"

        print(f"✅ 指定提供商客户端: {info['provider_name']}, 模型: {info['model']}")

    def test_get_provider_info(self):
        """测试获取提供商信息"""
        print("\n=== 测试获取提供商信息 ===")

        info = self.client.get_provider_info()

        assert isinstance(info, dict), "提供商信息应为字典"
        assert "provider_name" in info, "应包含 provider_name"
        assert "model" in info, "应包含 model"
        assert "temperature" in info, "应包含 temperature"
        assert "max_tokens" in info, "应包含 max_tokens"

        print(f"✅ 提供商信息:")
        print(f"   提供商: {info['provider_name']}")
        print(f"   模型: {info['model']}")
        print(f"   温度: {info['temperature']}")
        print(f"   最大 tokens: {info['max_tokens']}")

    def test_is_local_url(self):
        """测试本地 URL 判断"""
        print("\n=== 测试本地 URL 判断 ===")

        assert self.client._is_local_url("http://localhost:8000") is True
        assert self.client._is_local_url("http://127.0.0.1:8000") is True
        assert self.client._is_local_url("https://api.example.com") is False
        assert self.client._is_local_url("") is False

        print("✅ 本地 URL 判断正确")

    def test_get_model_creates_instance(self):
        """测试 get_model 创建模型实例（不调用远程 API）"""
        print("\n=== 测试 get_model 创建模型实例 ===")

        model = self.client.get_model()

        assert model is not None, "模型实例不应为空"
        assert self.client._model is model, "应使用缓存的模型实例"

        # 再次调用应返回同一实例
        model2 = self.client.get_model()
        assert model is model2, "应返回同一缓存实例"

        print("✅ get_model 返回有效实例并缓存")

    def test_refresh_model(self):
        """测试刷新模型实例"""
        print("\n=== 测试刷新模型实例 ===")

        self.client.get_model()
        assert self.client._model is not None, "首次调用后应有模型"

        self.client.refresh_model()
        assert self.client._model is None, "刷新后缓存应清空"

        print("✅ refresh_model 正确清空缓存")


class TestLLMClientGlobalFunctions:
    """测试 LLM 客户端全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_llm_client(self):
        """测试全局 get_llm_client 函数"""
        print("\n=== 测试全局 get_llm_client 函数 ===")

        client = get_llm_client()
        assert client is not None, "应返回 LLMClient 实例"
        assert isinstance(client, LLMClient), "类型应为 LLMClient"

        print("✅ get_llm_client 返回有效客户端")

    def test_get_llm_model(self):
        """测试全局 get_llm_model 函数"""
        print("\n=== 测试全局 get_llm_model 函数 ===")

        model = get_llm_model()
        assert model is not None, "应返回模型实例"

        print("✅ get_llm_model 返回有效模型")
