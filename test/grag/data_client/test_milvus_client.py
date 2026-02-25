"""测试 Milvus 客户端 (MilvusClient)"""

from grag.config import get_config_manager
from grag.data_client.milvus_client import MilvusClient, get_milvus_client


def _ensure_config():
    get_config_manager().initialize()


class TestMilvusClient:
    def setup_method(self):
        _ensure_config()
        self.client = MilvusClient()

    def test_init(self):
        print("\n=== 测试 Milvus 客户端初始化 ===")
        assert self.client is not None
        assert self.client._settings is not None
        print("✅ Milvus 客户端初始化成功")

    def test_get_config_info(self):
        print("\n=== 测试获取 Milvus 配置信息 ===")
        info = self.client.get_config_info()
        assert isinstance(info, dict)
        assert "provider" in info
        assert "host" in info
        assert "port" in info
        assert "collection_name" in info
        assert info["port"] == 19530
        print(f"✅ 配置信息: host={info.get('host')}, port={info.get('port')}")

    def test_get_collection_name(self):
        print("\n=== 测试获取集合名称 ===")
        name = self.client.get_collection_name()
        assert isinstance(name, str)
        assert len(name) > 0
        print(f"✅ collection_name: {name}")

    def test_connect_disconnect(self):
        print("\n=== 测试 connect / disconnect ===")
        try:
            self.client.connect()
            assert self.client._connected is True
            self.client.disconnect()
            assert self.client._connected is False
            print("✅ connect/disconnect 正常")
        except ImportError as e:
            print(f"⚠️ 未安装 pymilvus，跳过: {e}")
        except RuntimeError as e:
            if "连接" in str(e) or "connect" in str(e).lower():
                print("⚠️ Milvus 服务未启动，跳过连接测试")
            else:
                raise

    def test_test_connection(self):
        print("\n=== 测试 Milvus 连接检测 ===")
        result = self.client.test_connection()
        assert isinstance(result, bool)
        print(f"✅ test_connection 返回: {result}")


class TestMilvusGlobalFunctions:
    def setup_method(self):
        _ensure_config()

    def test_get_milvus_client(self):
        print("\n=== 测试全局 get_milvus_client ===")
        client = get_milvus_client()
        assert client is not None
        assert isinstance(client, MilvusClient)
        print("✅ get_milvus_client 返回有效客户端")
