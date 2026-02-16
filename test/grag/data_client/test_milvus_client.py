"""测试 Milvus 客户端 (MilvusClient)"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.config import initialize_config
from grag.data_client.milvus_client import MilvusClient, get_milvus_client


def _ensure_config():
    initialize_config()


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


def run_tests():
    print("\n" + "=" * 60)
    print("开始测试 MilvusClient 模块")
    print("=" * 60)
    t = TestMilvusClient()
    g = TestMilvusGlobalFunctions()
    try:
        t.setup_method(); t.test_init()
        t.setup_method(); t.test_get_config_info()
        t.setup_method(); t.test_get_collection_name()
        t.setup_method(); t.test_connect_disconnect()
        t.setup_method(); t.test_test_connection()
        g.setup_method(); g.test_get_milvus_client()
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        raise


if __name__ == "__main__":
    run_tests()
