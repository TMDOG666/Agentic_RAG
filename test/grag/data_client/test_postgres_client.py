"""测试 PostgreSQL 客户端 (PostgresClient)"""

from grag.config import get_config_manager
from grag.data_client.postgres_client import PostgresClient, get_postgres_client


def _ensure_config():
    get_config_manager().initialize()


class TestPostgresClient:
    def setup_method(self):
        _ensure_config()
        self.client = PostgresClient()

    def test_init(self):
        print("\n=== 测试 PostgreSQL 客户端初始化 ===")
        assert self.client is not None
        assert self.client._settings is not None
        print("✅ PostgreSQL 客户端初始化成功")

    def test_get_config_info(self):
        print("\n=== 测试获取 PostgreSQL 配置信息 ===")
        info = self.client.get_config_info()
        assert isinstance(info, dict), "get_config_info 应返回 dict"
        assert "provider" in info, "应包含 provider"
        assert "host" in info, "应包含 host"
        assert "port" in info, "应包含 port"
        assert "database" in info, "应包含 database"

        # 端口/数据库名以 grag_config.yaml 为准（不要在测试里写死 5432）
        assert isinstance(info["port"], int) and info["port"] > 0, "port 应为正整数"
        assert isinstance(info["database"], str) and len(info["database"]) > 0, "database 应为非空字符串"
        print(f"✅ 配置信息: host={info.get('host')}, database={info.get('database')}")

    def test_get_connect_params(self):
        print("\n=== 测试连接参数字典 ===")
        params = self.client._get_connect_params()
        assert "host" in params, "连接参数应包含 host"
        assert "port" in params, "连接参数应包含 port"
        assert "dbname" in params, "连接参数应包含 dbname"
        assert "user" in params, "连接参数应包含 user"
        assert "password" in params, "连接参数应包含 password"
        print("✅ _get_connect_params 包含必要键")

    def test_get_connection(self):
        print("\n=== 测试 get_connection ===")
        try:
            conn = self.client.get_connection()
            assert conn is not None
            conn.close()
            print("✅ get_connection 返回连接并已关闭")
        except ImportError as e:
            print(f"⚠️ 未安装 psycopg2，跳过: {e}")
        except RuntimeError as e:
            if "连接" in str(e) or "connect" in str(e).lower():
                print("⚠️ PostgreSQL 服务未启动，跳过连接测试")
            else:
                raise

    def test_test_connection(self):
        print("\n=== 测试 PostgreSQL 连接检测 ===")
        result = self.client.test_connection()
        assert isinstance(result, bool)
        print(f"✅ test_connection 返回: {result}")


class TestPostgresGlobalFunctions:
    def setup_method(self):
        _ensure_config()

    def test_get_postgres_client(self):
        print("\n=== 测试全局 get_postgres_client ===")
        client = get_postgres_client()
        assert client is not None
        assert isinstance(client, PostgresClient)
        print("✅ get_postgres_client 返回有效客户端")
