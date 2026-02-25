"""grag.data.neo4j_client

Neo4j 图数据库客户端

职责：
- 连接 Neo4j 图数据库，供知识图谱存储与查询
- 从 grag.config 读取连接配置（uri、user、password_env）
- 提供连接获取、健康检查、资源关闭

说明：
- 密码通过配置中的 password_env 从环境变量读取
- 支持连接池（由 Neo4j 驱动管理）
- 依赖：pip install neo4j
"""

import os
from typing import Optional, Any, Dict

from ..config import get_config_manager, ProviderType


def _get_driver():
    """延迟导入 neo4j 驱动，便于在未安装时给出明确错误"""
    try:
        from neo4j import GraphDatabase
        return GraphDatabase
    except ImportError as e:
        raise ImportError(
            "使用 Neo4j 客户端需要安装 neo4j 包: pip install neo4j"
        ) from e


class Neo4jClient:
    """Neo4j 图数据库客户端

    根据 grag_config 中 graph_databases.neo4j 的配置建立连接。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化 Neo4j 客户端

        Args:
            provider_name: 图数据库提供商名称，为 None 时使用配置中的默认值（如 neo4j）
        """
        self.provider_name = provider_name
        self._driver: Any = None
        self._settings = get_config_manager().get_settings()

    def _get_config(self):
        """获取当前提供商的 Neo4j 配置"""
        return self._settings.get_provider_config(
            ProviderType.GRAPH_DB,
            self.provider_name or self._settings.graph_db_provider,
        )

    def _get_password(self) -> Optional[str]:
        """从环境变量或配置直接读取密码"""
        config = self._get_config()
        # 优先从环境变量读取
        if getattr(config, "password_env", None):
            return os.environ.get(config.password_env)
        # 如果没有配置环境变量，直接从配置读取密码
        return getattr(config, "password", None)

    def get_driver(self):
        """获取或创建 Neo4j 驱动实例（懒加载）

        Returns:
            neo4j.Driver: 驱动实例，可用于创建 Session 执行 Cypher

        Raises:
            RuntimeError: 配置缺失或连接失败
        """
        if self._driver is not None:
            return self._driver

        config = self._get_config()
        uri = config.uri
        user = config.user
        password = self._get_password()

        if not uri:
            raise RuntimeError("Neo4j 配置缺少 uri")
        if not user:
            raise RuntimeError("Neo4j 配置缺少 user")
        # 如果配置声明了 password_env，但环境变量未设置，直接给出更明确的提示。
        # 这样可以避免服务端返回难以理解的“token 缺少 credentials”等错误。
        if password is None and getattr(config, "password_env", None):
            raise RuntimeError(
                f"未检测到 Neo4j 密码环境变量 {config.password_env}，请先设置后再连接。"
            )
        # 本地开发（或显式关闭鉴权）场景下，允许不提供密码：使用空字符串。
        if password is None:
            password = ""

        GraphDatabase = _get_driver()
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            return self._driver
        except Exception as e:
            raise RuntimeError(f"创建 Neo4j 驱动失败: {e}") from e

    def test_connection(self) -> bool:
        """验证与 Neo4j 的连接是否可用

        Returns:
            连接成功返回 True，否则 False
        """
        try:
            driver = self.get_driver()
            driver.verify_connectivity()
            return True
        except Exception as e:
            print(f"Neo4j 连接测试失败: {e}")
            return False

    def close(self) -> None:
        """关闭驱动，释放连接池"""
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:
                pass
            self._driver = None

    def get_config_info(self) -> Dict[str, Any]:
        """返回当前连接配置信息（不包含密码）"""
        config = self._get_config()
        return {
            "provider": self.provider_name or self._settings.graph_db_provider,
            "uri": config.uri,
            "user": config.user,
            "database": getattr(config, "database", None),
        }


# 全局单例，按需使用
_default_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client(provider_name: Optional[str] = None) -> Neo4jClient:
    """获取 Neo4j 客户端实例"""
    global _default_neo4j_client
    if _default_neo4j_client is None or provider_name is not None:
        _default_neo4j_client = Neo4jClient(provider_name)
    return _default_neo4j_client
