"""测试模型管理器 (ModelManager)"""

from grag.config import initialize_config
from grag.model.model_manager import (
    ModelManager,
    get_model_manager,
    initialize_models,
    get_llm_client,
    get_embedding_client,
    get_reranker_client,
    get_model_info,
    get_model_status,
)
from grag.model.llm_client import LLMClient
from grag.model.embedding_client import EmbeddingClient
from grag.model.reranker_client import RerankerClient


def _ensure_config():
    """确保配置已初始化"""
    initialize_config()


class TestModelManager:
    """测试 ModelManager 类"""

    def setup_method(self):
        """每个测试方法前执行"""
        _ensure_config()
        self.manager = ModelManager()

    def test_model_manager_init(self):
        """测试模型管理器初始化"""
        print("\n=== 测试模型管理器初始化 ===")

        assert self.manager is not None, "管理器不应为空"
        assert self.manager._settings is not None, "配置不应为空"
        assert self.manager._initialized is False, "初始时未执行 initialize()"

        print("✅ 模型管理器初始化成功")

    def test_get_llm_client(self):
        """测试获取 LLM 客户端"""
        print("\n=== 测试获取 LLM 客户端 ===")

        client = self.manager.get_llm_client()
        assert client is not None, "应返回 LLM 客户端"
        assert isinstance(client, LLMClient), "类型应为 LLMClient"

        # 同一提供商再次获取应返回同一实例
        client2 = self.manager.get_llm_client()
        assert client is client2, "应返回缓存的同一实例"

        print("✅ get_llm_client 返回有效客户端并缓存")

    def test_get_llm_client_with_provider(self):
        """测试指定提供商获取 LLM 客户端"""
        print("\n=== 测试指定提供商获取 LLM 客户端 ===")

        client = self.manager.get_llm_client(provider_name="siliconflow")
        assert client is not None
        assert client.provider_name == "siliconflow"

        print("✅ 指定提供商 LLM 客户端获取成功")

    def test_get_embedding_client(self):
        """测试获取嵌入客户端"""
        print("\n=== 测试获取嵌入客户端 ===")

        client = self.manager.get_embedding_client()
        assert client is not None
        assert isinstance(client, EmbeddingClient)

        client2 = self.manager.get_embedding_client()
        assert client is client2, "应返回缓存的同一实例"

        print("✅ get_embedding_client 返回有效客户端并缓存")

    def test_get_embedding_client_with_provider(self):
        """测试指定提供商获取嵌入客户端"""
        print("\n=== 测试指定提供商获取嵌入客户端 ===")

        client = self.manager.get_embedding_client(provider_name="siliconflow")
        assert client is not None
        assert client.provider_name == "siliconflow"

        print("✅ 指定提供商嵌入客户端获取成功")

    def test_get_reranker_client(self):
        """测试获取重排序客户端"""
        print("\n=== 测试获取重排序客户端 ===")

        client = self.manager.get_reranker_client()
        # 可能为 None（未配置重排序）
        if client is not None:
            assert isinstance(client, RerankerClient), "类型应为 RerankerClient"
            print("✅ get_reranker_client 返回有效客户端")
        else:
            print("✅ 重排序未配置，get_reranker_client 返回 None")

    def test_get_embedding_dimension(self):
        """测试获取嵌入维度"""
        print("\n=== 测试获取嵌入维度 ===")

        dim = self.manager.get_embedding_dimension()
        assert isinstance(dim, int), "维度应为整数"
        assert dim > 0, "维度应为正整数"

        print(f"✅ 嵌入维度: {dim}")

    def test_get_model_info(self):
        """测试获取模型配置信息"""
        print("\n=== 测试获取模型配置信息 ===")

        info = self.manager.get_model_info()

        assert isinstance(info, dict), "应返回字典"
        assert "llm" in info, "应包含 llm"
        assert "embedding" in info, "应包含 embedding"
        assert "reranker" in info, "应包含 reranker"
        assert "default_provider" in info["llm"], "llm 应包含 default_provider"
        assert "dimension" in info["embedding"], "embedding 应包含 dimension"

        print(f"✅ 模型信息:")
        print(f"   LLM 默认: {info['llm']['default_provider']}")
        print(f"   Embedding 默认: {info['embedding']['default_provider']}")
        print(f"   Embedding 维度: {info['embedding']['dimension']}")
        print(f"   Reranker 可用: {info['reranker'].get('available')}")

    def test_get_model_status(self):
        """测试获取模型状态（在获取客户端后）"""
        print("\n=== 测试获取模型状态 ===")

        # 先获取客户端以产生状态记录
        self.manager.get_llm_client()
        self.manager.get_embedding_client()

        status = self.manager.get_model_status()
        assert isinstance(status, dict), "应返回字典"
        # 至少应有 llm 和 embedding 的状态
        assert len(status) >= 2, "应至少有两个模型的状态记录"

        for key, val in status.items():
            assert "name" in val and "type" in val and "provider" in val, f"{key} 应包含 name/type/provider"

        print(f"✅ 模型状态记录数: {len(status)}")

    def test_refresh_all_models(self):
        """测试刷新所有模型"""
        print("\n=== 测试刷新所有模型 ===")

        self.manager.get_llm_client()
        self.manager.get_embedding_client()
        assert len(self.manager._llm_clients) >= 1, "应有 LLM 客户端缓存"
        assert len(self.manager._embedding_clients) >= 1, "应有嵌入客户端缓存"

        self.manager.refresh_all_models()
        assert len(self.manager._llm_clients) == 0, "刷新后 LLM 缓存应清空"
        assert len(self.manager._embedding_clients) == 0, "刷新后嵌入缓存应清空"

        print("✅ refresh_all_models 正确清空缓存")

    def test_refresh_model_single(self):
        """测试刷新单个模型"""
        print("\n=== 测试刷新单个模型 ===")

        self.manager.get_llm_client()
        self.manager.refresh_model("llm")
        # 刷新后该 provider 的客户端仍在字典中，但内部 _model 被清空
        # 具体行为以实现为准，这里只验证不抛异常
        print("✅ refresh_model('llm') 执行成功")

    def test_cleanup(self):
        """测试清理资源"""
        print("\n=== 测试清理资源 ===")

        self.manager.get_llm_client()
        self.manager.cleanup()

        assert len(self.manager._llm_clients) == 0, "清理后 LLM 缓存应清空"
        assert len(self.manager._embedding_clients) == 0, "清理后嵌入缓存应清空"
        assert self.manager._initialized is False, "清理后应标记未初始化"

        print("✅ cleanup 正确释放资源")


class TestModelManagerInitialize:
    """测试模型管理器初始化（会尝试连接，可能因无 API Key 而仅打印警告）"""

    def setup_method(self):
        _ensure_config()

    def test_initialize_models(self):
        """测试 initialize_models（不强制要求连接成功）"""
        print("\n=== 测试 initialize_models ===")

        success = initialize_models()
        assert isinstance(success, bool), "应返回布尔值"
        # 即使连接失败，当前实现也可能返回 True（仅打印警告）
        print(f"✅ initialize_models 返回: {success}")


class TestModelManagerGlobalFunctions:
    """测试模型管理器全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_model_manager(self):
        """测试全局 get_model_manager 函数"""
        print("\n=== 测试全局 get_model_manager 函数 ===")

        manager = get_model_manager()
        assert manager is not None
        assert isinstance(manager, ModelManager)

        manager2 = get_model_manager()
        assert manager is manager2, "应返回同一单例"

        print("✅ get_model_manager 返回单例")

    def test_global_get_llm_client(self):
        """测试全局 get_llm_client"""
        print("\n=== 测试全局 get_llm_client ===")

        client = get_llm_client()
        assert client is not None
        assert isinstance(client, LLMClient)
        print("✅ get_llm_client 返回有效客户端")

    def test_global_get_embedding_client(self):
        """测试全局 get_embedding_client"""
        print("\n=== 测试全局 get_embedding_client ===")

        client = get_embedding_client()
        assert client is not None
        assert isinstance(client, EmbeddingClient)
        print("✅ get_embedding_client 返回有效客户端")

    def test_global_get_model_info(self):
        """测试全局 get_model_info"""
        print("\n=== 测试全局 get_model_info ===")

        info = get_model_info()
        assert info is not None
        assert "llm" in info and "embedding" in info
        print("✅ get_model_info 返回有效信息")

    def test_global_get_model_status(self):
        """测试全局 get_model_status"""
        print("\n=== 测试全局 get_model_status ===")

        get_llm_client()  # 确保有状态
        status = get_model_status()
        assert isinstance(status, dict)
        print(f"✅ get_model_status 返回 {len(status)} 条状态")

    def test_global_get_embedding_dimension(self):
        """测试通过 manager 获取嵌入维度"""
        print("\n=== 测试通过 manager 获取嵌入维度 ===")

        manager = get_model_manager()
        dim = manager.get_embedding_dimension()
        assert isinstance(dim, int) and dim > 0
        print(f"✅ get_embedding_dimension = {dim}")
