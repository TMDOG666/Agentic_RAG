"""测试 Neo4j 客户端 (Neo4jClient)"""

from grag.config import get_config_manager
from grag.data_client.neo4j_client import Neo4jClient, get_neo4j_client


def _ensure_config():
    get_config_manager().initialize()


class TestNeo4jClient:
    def setup_method(self):
        _ensure_config()
        self.client = Neo4jClient()

    def test_init(self):
        print("\n=== 测试 Neo4j 客户端初始化 ===")
        assert self.client is not None
        assert self.client._settings is not None
        print("✅ Neo4j 客户端初始化成功")

    def test_get_config_info(self):
        print("\n=== 测试获取 Neo4j 配置信息 ===")
        info = self.client.get_config_info()
        assert isinstance(info, dict)
        assert "provider" in info
        assert "uri" in info
        assert "user" in info
        assert info["user"] == "neo4j"
        print(f"✅ 配置信息: uri={info.get('uri')}, user={info.get('user')}")

    def test_client_with_provider(self):
        print("\n=== 测试指定提供商 Neo4j 客户端 ===")
        client = Neo4jClient(provider_name="neo4j")
        info = client.get_config_info()
        assert info["provider"] == "neo4j"
        print("✅ 指定提供商 neo4j 配置正确")

    def test_get_driver_requires_config(self):
        print("\n=== 测试 get_driver 使用配置 ===")
        try:
            driver = self.client.get_driver()
            assert driver is not None
            self.client.close()
            print("✅ get_driver 返回驱动实例（已关闭）")
        except ImportError as e:
            print(f"⚠️ 未安装 neo4j 驱动，跳过: {e}")
        except RuntimeError as e:
            if "连接" in str(e) or "connect" in str(e).lower():
                print("⚠️ Neo4j 服务未启动，get_driver 连接失败（预期）")
            else:
                raise

    def test_test_connection(self):
        print("\n=== 测试 Neo4j 连接检测 ===")
        result = self.client.test_connection()
        assert isinstance(result, bool)
        print(f"✅ test_connection 返回: {result}")

    def test_close(self):
        print("\n=== 测试 close 释放资源 ===")
        try:
            self.client.get_driver()
            self.client.close()
            assert self.client._driver is None
        except (ImportError, RuntimeError):
            self.client._driver = None
        print("✅ close 执行正常")


class TestNeo4jGlobalFunctions:
    def setup_method(self):
        _ensure_config()

    def test_get_neo4j_client(self):
        print("\n=== 测试全局 get_neo4j_client ===")
        client = get_neo4j_client()
        assert client is not None
        assert isinstance(client, Neo4jClient)
        print("✅ get_neo4j_client 返回有效客户端")
