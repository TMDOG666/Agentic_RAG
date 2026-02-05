"""测试重排序客户端 (RerankerClient)"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.config import initialize_config
from grag.model.reranker_client import (
    RerankerClient,
    get_reranker_client,
    is_reranker_available,
    rerank_documents,
)


def _ensure_config():
    """确保配置已初始化"""
    initialize_config()


class TestRerankerClient:
    """测试 RerankerClient 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        _ensure_config()
        self.client = RerankerClient()

    def test_reranker_client_init(self):
        """测试重排序客户端初始化"""
        print("\n=== 测试重排序客户端初始化 ===")

        assert self.client is not None, "客户端不应为空"
        assert self.client._settings is not None, "配置不应为空"

        print("✅ 重排序客户端初始化成功")

    def test_is_available(self):
        """测试重排序服务是否可用"""
        print("\n=== 测试重排序服务是否可用 ===")

        available = self.client.is_available()
        assert isinstance(available, bool), "应返回布尔值"

        print(f"✅ 重排序可用: {available}")

    def test_get_provider_info(self):
        """测试获取提供商信息"""
        print("\n=== 测试获取提供商信息 ===")

        info = self.client.get_provider_info()
        assert isinstance(info, dict), "提供商信息应为字典"
        assert "available" in info, "应包含 available"

        if info.get("available"):
            assert "provider_name" in info
            assert "model" in info
            print(f"✅ 提供商信息: {info.get('provider_name')}, 模型: {info.get('model')}")
        else:
            print("✅ 重排序未配置，info.available=False")

    def test_rerank_returns_list(self):
        """测试 rerank 返回格式（不依赖真实 API）"""
        print("\n=== 测试 rerank 返回格式 ===")

        query = "test query"
        documents = ["doc1", "doc2", "doc3"]
        result = self.client.rerank(query, documents, top_k=2)

        assert isinstance(result, list), "应返回列表"
        assert len(result) <= 2, "top_k=2 时最多返回 2 条"
        for item in result:
            assert isinstance(item, tuple), "每项应为 (document, score) 元组"
            assert len(item) == 2, "元组应包含 document 和 score"

        print(f"✅ rerank 返回 {len(result)} 条结果，格式正确")

    def test_rerank_without_top_k(self):
        """测试不指定 top_k 时返回全部"""
        print("\n=== 测试 rerank 不指定 top_k ===")

        documents = ["a", "b", "c"]
        result = self.client.rerank("q", documents)
        assert len(result) == 3, "应返回全部 3 条"

        print("✅ 不指定 top_k 时返回全部文档")

    def test_refresh_reranker(self):
        """测试刷新重排序器"""
        print("\n=== 测试刷新重排序器 ===")

        if self.client.is_available():
            self.client.get_reranker()
            self.client.refresh_reranker()
            assert self.client._reranker is None, "刷新后应为 None"
        print("✅ refresh_reranker 正确清空缓存")


class TestRerankerClientGlobalFunctions:
    """测试重排序客户端全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_reranker_client(self):
        """测试全局 get_reranker_client 函数"""
        print("\n=== 测试全局 get_reranker_client 函数 ===")

        client = get_reranker_client()
        assert client is not None
        assert isinstance(client, RerankerClient)

        print("✅ get_reranker_client 返回有效客户端")

    def test_is_reranker_available(self):
        """测试全局 is_reranker_available 函数"""
        print("\n=== 测试全局 is_reranker_available 函数 ===")

        available = is_reranker_available()
        assert isinstance(available, bool)

        print(f"✅ is_reranker_available = {available}")

    def test_rerank_documents(self):
        """测试全局 rerank_documents 函数"""
        print("\n=== 测试全局 rerank_documents 函数 ===")

        result = rerank_documents("query", ["d1", "d2"], top_k=1)
        assert isinstance(result, list)
        assert len(result) == 1

        print("✅ rerank_documents 返回格式正确")


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始测试 RerankerClient 模块")
    print("=" * 60)

    test_class = TestRerankerClient()
    test_global = TestRerankerClientGlobalFunctions()

    try:
        test_class.setup_method()
        test_class.test_reranker_client_init()

        test_class.setup_method()
        test_class.test_is_available()

        test_class.setup_method()
        test_class.test_get_provider_info()

        test_class.setup_method()
        test_class.test_rerank_returns_list()

        test_class.setup_method()
        test_class.test_rerank_without_top_k()

        test_class.setup_method()
        test_class.test_refresh_reranker()

        test_global.setup_method()
        test_global.test_get_reranker_client()

        test_global.setup_method()
        test_global.test_is_reranker_available()

        test_global.setup_method()
        test_global.test_rerank_documents()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

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
