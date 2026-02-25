"""测试数据层管理器 (DataManager)"""

from grag.config import get_config_manager
from grag.data_client import (
    DataManager,
    get_data_manager,
    Neo4jClient,
    MilvusClient,
    PostgresClient,
)


def _ensure_config():
    get_config_manager().initialize()


class TestDataManager:
    def setup_method(self):
        _ensure_config()
        self.manager = DataManager()

    def test_init(self):
        print("\n=== 测试 DataManager 初始化 ===")
        assert self.manager is not None
        assert self.manager._settings is not None
        print("✅ DataManager 初始化成功")

    def test_get_neo4j_client(self):
        print("\n=== 测试 get_neo4j_client ===")
        client = self.manager.get_neo4j_client()
        assert client is not None
        assert isinstance(client, Neo4jClient)
        client2 = self.manager.get_neo4j_client()
        assert client is client2
        print("✅ get_neo4j_client 返回并缓存客户端")

    def test_get_milvus_client(self):
        print("\n=== 测试 get_milvus_client ===")
        client = self.manager.get_milvus_client()
        assert client is not None
        assert isinstance(client, MilvusClient)
        client2 = self.manager.get_milvus_client()
        assert client is client2
        print("✅ get_milvus_client 返回并缓存客户端")

    def test_get_postgres_client(self):
        print("\n=== 测试 get_postgres_client ===")
        client = self.manager.get_postgres_client()
        assert client is not None
        assert isinstance(client, PostgresClient)
        client2 = self.manager.get_postgres_client()
        assert client is client2
        print("✅ get_postgres_client 返回并缓存客户端")

    def test_get_config_info(self):
        print("\n=== 测试 get_config_info ===")
        info = self.manager.get_config_info()
        assert isinstance(info, dict)
        assert "neo4j" in info
        assert "milvus" in info
        assert "postgres" in info
        assert "uri" in info["neo4j"]
        assert "collection_name" in info["milvus"]
        assert "database" in info["postgres"]
        print("✅ get_config_info 返回三库配置")

    def test_test_all_connections(self):
        print("\n=== 测试 test_all_connections ===")
        result = self.manager.test_all_connections()
        assert isinstance(result, dict)
        assert "neo4j" in result
        assert "milvus" in result
        assert "postgres" in result
        assert isinstance(result["neo4j"], bool)
        assert isinstance(result["milvus"], bool)
        assert isinstance(result["postgres"], bool)
        print(f"✅ 连接结果: neo4j={result['neo4j']}, milvus={result['milvus']}, postgres={result['postgres']}")

    def test_cleanup(self):
        print("\n=== 测试 cleanup ===")
        self.manager.get_neo4j_client()
        self.manager.get_milvus_client()
        self.manager.get_postgres_client()
        self.manager.cleanup()
        assert self.manager._neo4j is None
        assert self.manager._milvus is None
        assert self.manager._postgres is None
        print("✅ cleanup 已清空客户端缓存")


class TestDataManagerGlobalFunctions:
    def setup_method(self):
        _ensure_config()

    def test_get_data_manager(self):
        print("\n=== 测试全局 get_data_manager ===")
        manager = get_data_manager()
        assert manager is not None
        assert isinstance(manager, DataManager)
        manager2 = get_data_manager()
        assert manager is manager2
        print("✅ get_data_manager 返回单例")
