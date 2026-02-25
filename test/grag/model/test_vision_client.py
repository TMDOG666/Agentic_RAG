"""测试视觉模型客户端 (VisionClient)"""

from grag.config import get_config_manager, ProviderType
from grag.model import VisionClient, get_vision_client


def _ensure_config():
    """确保配置已初始化"""
    get_config_manager().initialize()


class TestVisionClient:
    """测试 VisionClient 类"""

    def setup_method(self):
        _ensure_config()
        self.client = VisionClient()

    def test_init(self):
        print("\n=== 测试 VisionClient 初始化 ===")
        assert self.client is not None
        assert self.client._settings is not None
        print("✅ VisionClient 初始化成功")

    def test_get_config_info(self):
        print("\n=== 测试获取视觉模型配置信息 ===")
        info = self.client.get_config_info()
        assert isinstance(info, dict), "get_config_info 应返回 dict"
        assert "provider" in info
        assert "model" in info
        assert "base_url" in info
        assert "timeout" in info

        settings = get_config_manager().get_settings()
        vision_cfg = settings.get_provider_config(ProviderType.VISION)

        assert info["provider"] == settings.vision_provider, "视觉提供商应与配置一致"
        assert info["model"] == vision_cfg.model, "视觉模型名称应与配置一致"
        assert info["base_url"] == vision_cfg.base_url, "视觉 base_url 应与配置一致"

        print("✅ 视觉模型配置与 grag_config.yaml 一致")

    def test_get_client_lazy(self):
        """仅测试懒加载逻辑，不强制要求 openai 已安装"""
        print("\n=== 测试 VisionClient 客户端懒加载 ===")
        try:
            client1 = self.client._get_client()
            assert client1 is not None
            client2 = self.client._get_client()
            assert client1 is client2, "_get_client 应缓存实例"
            print("✅ _get_client 懒加载并缓存实例")
        except ImportError as e:
            print(f"⚠️ 未安装 openai，跳过客户端创建测试: {e}")


class TestVisionGlobalFunctions:
    """测试视觉模型全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_vision_client(self):
        print("\n=== 测试全局 get_vision_client ===")
        client = get_vision_client()
        assert client is not None
        assert isinstance(client, VisionClient)
        client2 = get_vision_client()
        assert client is client2, "get_vision_client 应返回单例"
        print("✅ get_vision_client 返回 VisionClient 单例")

