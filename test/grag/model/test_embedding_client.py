"""测试嵌入客户端 (EmbeddingClient)"""

import os

from grag.config import initialize_config
from grag.model.embedding_client import (
    EmbeddingClient,
    get_embedding_client,
    get_embeddings,
)


def _ensure_config():
    """确保配置已初始化"""
    initialize_config()


class TestEmbeddingClient:
    """测试 EmbeddingClient 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        _ensure_config()
        self.client = EmbeddingClient()

    def test_embedding_client_init(self):
        """测试嵌入客户端初始化"""
        print("\n=== 测试嵌入客户端初始化 ===")

        assert self.client is not None, "客户端不应为空"
        assert self.client._settings is not None, "配置不应为空"

        print("✅ 嵌入客户端初始化成功")

    def test_embedding_client_with_provider(self):
        """测试指定提供商的嵌入客户端"""
        print("\n=== 测试指定提供商的嵌入客户端 ===")

        client = EmbeddingClient(provider_name="siliconflow")
        assert client.provider_name == "siliconflow"

        info = client.get_provider_info()
        assert info["provider_name"] == "siliconflow"
        assert "dimension" in info, "应包含 dimension"

        print(f"✅ 指定提供商: {info['provider_name']}, 维度: {info['dimension']}")

    def test_get_provider_info(self):
        """测试获取提供商信息"""
        print("\n=== 测试获取提供商信息 ===")

        info = self.client.get_provider_info()

        assert isinstance(info, dict), "提供商信息应为字典"
        assert "provider_name" in info, "应包含 provider_name"
        assert "model" in info, "应包含 model"
        assert "dimension" in info, "应包含 dimension"
        assert info["dimension"] > 0, "维度应为正整数"

        print(f"✅ 提供商信息: 模型={info['model']}, 维度={info['dimension']}")

    def test_get_dimension(self):
        """测试获取嵌入维度"""
        print("\n=== 测试获取嵌入维度 ===")

        dim = self.client.get_dimension()
        assert isinstance(dim, int), "维度应为整数"
        assert dim > 0, "维度应为正整数"

        print(f"✅ 嵌入维度: {dim}")

    def test_get_embeddings_creates_instance(self):
        """测试 get_embeddings 创建嵌入实例"""
        print("\n=== 测试 get_embeddings 创建嵌入实例 ===")

        embeddings = self.client.get_embeddings()
        assert embeddings is not None, "嵌入实例不应为空"
        assert self.client._embeddings is embeddings, "应使用缓存实例"

        embeddings2 = self.client.get_embeddings()
        assert embeddings is embeddings2, "应返回同一缓存实例"

        print("✅ get_embeddings 返回有效实例并缓存")

    def test_refresh_embeddings(self):
        """测试刷新嵌入实例"""
        print("\n=== 测试刷新嵌入实例 ===")

        self.client.get_embeddings()
        assert self.client._embeddings is not None

        self.client.refresh_embeddings()
        assert self.client._embeddings is None, "刷新后缓存应清空"

        print("✅ refresh_embeddings 正确清空缓存")


class TestEmbeddingClientGlobalFunctions:
    """测试嵌入客户端全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_embedding_client(self):
        """测试全局 get_embedding_client 函数"""
        print("\n=== 测试全局 get_embedding_client 函数 ===")

        client = get_embedding_client()
        assert client is not None
        assert isinstance(client, EmbeddingClient)

        print("✅ get_embedding_client 返回有效客户端")

    def test_get_embeddings(self):
        """测试全局 get_embeddings 函数"""
        print("\n=== 测试全局 get_embeddings 函数 ===")

        embeddings = get_embeddings()
        assert embeddings is not None

        print("✅ get_embeddings 返回有效嵌入实例")
