"""grag.data.milvus_client

Milvus 向量数据库客户端

职责：
- 连接 Milvus 向量库，供文档/实体向量存储与相似度检索
- 从 grag.config 读取连接配置（host、port、collection_name 等）
- 提供连接管理、集合访问、健康检查

说明：
- 对应 config 中 vector_databases.milvus
- 依赖：pip install pymilvus
"""

import os
from typing import Optional, Any, Dict

from ..config import get_config_manager, ProviderType


def _ensure_milvus():
    """延迟导入 pymilvus，未安装时给出明确错误"""
    try:
        import pymilvus
        return pymilvus
    except ImportError as e:
        raise ImportError(
            "使用 Milvus 客户端需要安装 pymilvus: pip install pymilvus"
        ) from e


# 默认连接别名，便于多实例时区分
DEFAULT_ALIAS = "default"


class MilvusClient:
    """Milvus 向量数据库客户端

    根据 grag_config 中 vector_databases.milvus 的配置建立连接。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化 Milvus 客户端

        Args:
            provider_name: 向量库提供商名称，为 None 时使用配置中的默认值（如 milvus）
        """
        self.provider_name = provider_name
        self._connected = False
        self._alias = DEFAULT_ALIAS
        self._settings = get_config_manager().get_settings()

    def _get_config(self):
        """获取当前提供商的 Milvus 配置"""
        return self._settings.get_provider_config(
            ProviderType.VECTOR_DB,
            self.provider_name or self._settings.vector_db_provider,
        )

    def connect(self) -> None:
        """建立与 Milvus 的连接（懒加载，重复调用不会重复连接）"""
        if self._connected:
            return

        pymilvus = _ensure_milvus()
        config = self._get_config()
        host = config.host or "localhost"
        port = config.port or 19530
        user = getattr(config, "user", None)
        password = getattr(config, "password", None)
        if getattr(config, "password_env", None):
            password = os.environ.get(config.password_env) or password
        timeout = getattr(config, "connection_timeout", 30) or 30

        try:
            pymilvus.connections.connect(
                alias=self._alias,
                host=host,
                port=port,
                user=user,
                password=password,
                timeout=timeout,
            )
            self._connected = True
        except Exception as e:
            raise RuntimeError(f"连接 Milvus 失败: {e}") from e

    def disconnect(self) -> None:
        """断开与 Milvus 的连接"""
        if not self._connected:
            return
        try:
            _ensure_milvus().connections.disconnect(self._alias)
        except Exception:
            pass
        self._connected = False

    def get_collection_name(self) -> str:
        """返回配置中的集合名称"""
        config = self._get_config()
        return config.collection_name

    def test_connection(self) -> bool:
        """验证与 Milvus 的连接是否可用

        Returns:
            连接成功返回 True，否则 False
        """
        try:
            self.connect()
            # 简单列出 collection 或执行 has_collection 作为探活
            pymilvus = _ensure_milvus()
            pymilvus.utility.get_server_version()
            return True
        except Exception as e:
            print(f"Milvus 连接测试失败: {e}")
            return False

    def get_config_info(self) -> Dict[str, Any]:
        """返回当前连接配置信息"""
        config = self._get_config()
        return {
            "provider": self.provider_name or self._settings.vector_db_provider,
            "host": config.host,
            "port": config.port,
            "db_name": getattr(config, "db_name", None),
            "collection_name": config.collection_name,
        }


_default_milvus_client: Optional[MilvusClient] = None


def get_milvus_client(provider_name: Optional[str] = None) -> MilvusClient:
    """获取 Milvus 客户端实例"""
    global _default_milvus_client
    if _default_milvus_client is None or provider_name is not None:
        _default_milvus_client = MilvusClient(provider_name)
    return _default_milvus_client
