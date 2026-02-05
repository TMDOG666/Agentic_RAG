"""grag.data.data_manager

数据层管理器

职责：
- 统一管理 Neo4j、Milvus、PostgreSQL 三个数据库客户端
- 从 grag.config 读取默认提供商，按需创建客户端
- 提供连接测试、资源清理

说明：
- 使用前需先调用 grag.config.initialize_config() 加载配置
- 各客户端懒加载，首次访问时创建
"""

from typing import Optional, Dict, Any

from ..config import get_grag_settings, ProviderType
from .neo4j_client import Neo4jClient, get_neo4j_client
from .milvus_client import MilvusClient, get_milvus_client
from .postgres_client import PostgresClient, get_postgres_client


class DataManager:
    """数据层管理器

    统一持有并暴露图库、向量库、关系库客户端，与 grag_config 中的
    graph_db_provider、vector_db_provider、relational_db_provider 一致。
    """

    def __init__(self):
        self._settings = get_grag_settings()
        self._neo4j: Optional[Neo4jClient] = None
        self._milvus: Optional[MilvusClient] = None
        self._postgres: Optional[PostgresClient] = None

    def get_neo4j_client(self, provider_name: Optional[str] = None) -> Neo4jClient:
        """获取 Neo4j 图数据库客户端"""
        if provider_name is not None:
            return Neo4jClient(provider_name)
        if self._neo4j is None:
            self._neo4j = Neo4jClient(
                self._settings.graph_db_provider
            )
        return self._neo4j

    def get_milvus_client(self, provider_name: Optional[str] = None) -> MilvusClient:
        """获取 Milvus 向量数据库客户端"""
        if provider_name is not None:
            return MilvusClient(provider_name)
        if self._milvus is None:
            self._milvus = MilvusClient(
                self._settings.vector_db_provider
            )
        return self._milvus

    def get_postgres_client(
        self, provider_name: Optional[str] = None
    ) -> PostgresClient:
        """获取 PostgreSQL 关系数据库客户端"""
        if provider_name is not None:
            return PostgresClient(provider_name)
        if self._postgres is None:
            self._postgres = PostgresClient(
                self._settings.relational_db_provider
            )
        return self._postgres

    def test_all_connections(self) -> Dict[str, bool]:
        """测试三个数据库连接是否可用

        Returns:
            键为 neo4j / milvus / postgres，值为是否连接成功
        """
        result = {}
        try:
            result["neo4j"] = self.get_neo4j_client().test_connection()
        except Exception as e:
            print(f"Neo4j 测试异常: {e}")
            result["neo4j"] = False
        try:
            result["milvus"] = self.get_milvus_client().test_connection()
        except Exception as e:
            print(f"Milvus 测试异常: {e}")
            result["milvus"] = False
        try:
            result["postgres"] = self.get_postgres_client().test_connection()
        except Exception as e:
            print(f"Postgres 测试异常: {e}")
            result["postgres"] = False
        return result

    def get_config_info(self) -> Dict[str, Any]:
        """返回三个库的配置摘要（不包含密码）"""
        return {
            "neo4j": self.get_neo4j_client().get_config_info(),
            "milvus": self.get_milvus_client().get_config_info(),
            "postgres": self.get_postgres_client().get_config_info(),
        }

    def cleanup(self) -> None:
        """释放连接资源"""
        if self._neo4j is not None:
            self._neo4j.close()
            self._neo4j = None
        if self._milvus is not None:
            self._milvus.disconnect()
            self._milvus = None
        # PostgresClient 不持有长连接，无需关闭
        self._postgres = None


_default_data_manager: Optional[DataManager] = None


def get_data_manager() -> DataManager:
    """获取数据层管理器单例"""
    global _default_data_manager
    if _default_data_manager is None:
        _default_data_manager = DataManager()
    return _default_data_manager
