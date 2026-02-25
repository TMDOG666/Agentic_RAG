"""grag.data.postgres_client

PostgreSQL 关系数据库客户端

职责：
- 连接 PostgreSQL，供元数据、流水记录等关系型存储
- 从 grag.config 读取连接配置（host、port、database、user、password_env 等）
- 提供连接获取、健康检查、资源关闭

说明：
- 对应 config 中 relational_databases.postgres
- 密码通过 password_env 从环境变量读取
- 依赖：pip install psycopg2-binary
"""

import os
from typing import Optional, Any, Dict

from ..config import get_config_manager, ProviderType


def _get_psycopg2():
    """延迟导入 psycopg2，未安装时给出明确错误"""
    try:
        import psycopg2
        return psycopg2
    except ImportError as e:
        raise ImportError(
            "使用 PostgreSQL 客户端需要安装: pip install psycopg2-binary"
        ) from e


class PostgresClient:
    """PostgreSQL 关系数据库客户端

    根据 grag_config 中 relational_databases.postgres 的配置建立连接。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化 PostgreSQL 客户端

        Args:
            provider_name: 关系库提供商名称，为 None 时使用配置中的默认值（如 postgres）
        """
        self.provider_name = provider_name
        self._conn: Any = None
        self._settings = get_config_manager().get_settings()

    def _get_config(self):
        """获取当前提供商的 PostgreSQL 配置"""
        return self._settings.get_provider_config(
            ProviderType.RELATIONAL_DB,
            self.provider_name or self._settings.relational_db_provider,
        )

    def _get_password(self) -> Optional[str]:
        """从环境变量或配置直接读取密码"""
        config = self._get_config()
        # 优先从环境变量读取
        if getattr(config, "password_env", None):
            return os.environ.get(config.password_env)
        # 如果没有配置环境变量，直接从配置读取密码
        return getattr(config, "password", None)

    def _get_connect_params(self) -> Dict[str, Any]:
        """组装 psycopg2.connect 参数字典"""
        config = self._get_config()
        password = self._get_password()
        # 如果配置声明了 password_env，但环境变量未设置，给出更明确的提示。
        # 注意：这里不直接 raise，避免“只想读取配置/跑单测”就失败；
        # 真正建立连接时（get_connection/test_connection）再根据该情况给出错误提示。
        password_env = getattr(config, "password_env", None)
        params = {
            "host": config.host or "localhost",
            "port": config.port or 5432,
            "dbname": config.database or "grag",
            "user": config.user or "postgres",
            "password": password or "",
            "connect_timeout": getattr(config, "connection_timeout", 30) or 30,
        }
        if getattr(config, "sslmode", None) or getattr(config, "ssl_mode", None):
            params["sslmode"] = getattr(config, "ssl_mode", None) or getattr(
                config, "sslmode", "prefer"
            )
        return params

    def get_connection(self):
        """获取或创建数据库连接（懒加载；每次返回新连接，调用方负责关闭）

        如需长连接复用，可保留返回的 connection 并在用完后调用 conn.close()。
        本方法不缓存 connection，避免跨线程/跨请求共用同一连接导致的问题。

        Returns:
            psycopg2.connection: 数据库连接实例
        """
        psycopg2 = _get_psycopg2()
        config = self._get_config()
        params = self._get_connect_params()
        # 只有在配置了 password_env 但环境变量未设置时才报错
        # 如果直接配置了 password 或者没有配置任何密码，则允许继续
        if (
            (not params.get("password"))
            and getattr(config, "password_env", None)
            and not os.environ.get(config.password_env)
        ):
            raise RuntimeError(
                f"未检测到 PostgreSQL 密码环境变量 {config.password_env}，请先设置后再连接。"
            )
        try:
            return psycopg2.connect(**params)
        except Exception as e:
            raise RuntimeError(f"连接 PostgreSQL 失败: {e}") from e

    def test_connection(self) -> bool:
        """验证与 PostgreSQL 的连接是否可用

        Returns:
            连接成功返回 True，否则 False
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception as e:
            print(f"PostgreSQL 连接测试失败: {e}")
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_config_info(self) -> Dict[str, Any]:
        """返回当前连接配置信息（不包含密码）"""
        config = self._get_config()
        return {
            "provider": self.provider_name or self._settings.relational_db_provider,
            "host": config.host,
            "port": config.port,
            "database": config.database,
            "user": config.user,
            "schema": getattr(config, "db_schema", "public"),
        }


_default_postgres_client: Optional[PostgresClient] = None


def get_postgres_client(provider_name: Optional[str] = None) -> PostgresClient:
    """获取 PostgreSQL 客户端实例"""
    global _default_postgres_client
    if _default_postgres_client is None or provider_name is not None:
        _default_postgres_client = PostgresClient(provider_name)
    return _default_postgres_client
