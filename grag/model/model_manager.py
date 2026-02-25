"""grag.model.model_manager

模型管理器（Model Manager）

职责：
- 统一管理所有AI模型（LLM、嵌入、重排序）
- 提供模型的初始化、缓存和切换
- 处理模型间的联动和配置同步
- 提供模型健康检查和监控

说明：
- 作为model层的统一入口
- 实现模型的懒加载和缓存
- 提供模型切换和配置更新
- 支持模型的批量操作

设计模式：
- 单例模式：全局唯一的模型管理器
- 工厂模式：根据配置创建不同类型的模型
- 缓存模式：避免重复创建模型实例
"""

import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

from .llm_client import LLMClient, get_llm_model, test_llm_connection
from .embedding_client import EmbeddingClient, get_embeddings, test_embedding_connection
from .reranker_client import RerankerClient, rerank_documents, is_reranker_available, test_reranker_connection
from ..config import get_config_manager, ProviderType


@dataclass
class ModelStatus:
    """模型状态信息"""
    name: str
    type: str
    provider: str
    initialized: bool
    last_used: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None


class ModelManager:
    """模型管理器

    统一管理GraphRAG中的所有AI模型，提供初始化、缓存、监控等功能。
    """

    def __init__(self):
        """初始化模型管理器"""
        self._settings = get_config_manager().get_settings()

        # 模型实例缓存
        self._llm_clients: Dict[str, LLMClient] = {}
        self._embedding_clients: Dict[str, EmbeddingClient] = {}
        self._reranker_clients: Dict[str, RerankerClient] = {}

        # 模型状态跟踪
        self._model_status: Dict[str, ModelStatus] = {}

        # 初始化标志
        self._initialized = False

    def initialize(self) -> bool:
        """初始化所有模型

        Returns:
            初始化是否成功
        """
        try:
            # 测试默认模型连接
            print("初始化LLM模型...")
            if not test_llm_connection():
                print("警告: LLM模型连接测试失败")
            else:
                print("LLM模型连接正常")

            print("初始化嵌入模型...")
            if not test_embedding_connection():
                print("警告: 嵌入模型连接测试失败")
            else:
                print("嵌入模型连接正常")

            if is_reranker_available():
                print("初始化重排序模型...")
                if not test_reranker_connection():
                    print("警告: 重排序模型连接测试失败")
                else:
                    print("重排序模型连接正常")
            else:
                print("重排序模型未配置，跳过")

            self._initialized = True
            print("所有模型初始化完成")
            return True

        except Exception as e:
            print(f"模型初始化失败: {e}")
            self._initialized = False
            return False

    def is_initialized(self) -> bool:
        """检查是否已初始化

        Returns:
            是否已初始化
        """
        return self._initialized

    def get_llm_client(self, provider_name: Optional[str] = None) -> LLMClient:
        """获取LLM客户端

        Args:
            provider_name: 提供商名称

        Returns:
            LLMClient实例
        """
        provider = provider_name or self._settings.llm_provider

        if provider not in self._llm_clients:
            self._llm_clients[provider] = LLMClient(provider)

            # 记录状态
            self._update_model_status(f"llm_{provider}", "llm", provider)

        # 更新使用时间
        self._update_last_used(f"llm_{provider}")

        return self._llm_clients[provider]

    def get_embedding_client(self, provider_name: Optional[str] = None) -> EmbeddingClient:
        """获取嵌入客户端

        Args:
            provider_name: 提供商名称

        Returns:
            EmbeddingClient实例
        """
        provider = provider_name or self._settings.embedding_provider

        if provider not in self._embedding_clients:
            self._embedding_clients[provider] = EmbeddingClient(provider)

            # 记录状态
            self._update_model_status(f"embedding_{provider}", "embedding", provider)

        # 更新使用时间
        self._update_last_used(f"embedding_{provider}")

        return self._embedding_clients[provider]

    def get_reranker_client(self, provider_name: Optional[str] = None) -> RerankerClient:
        """获取重排序客户端

        Args:
            provider_name: 提供商名称

        Returns:
            RerankerClient实例
        """
        provider = provider_name or self._settings.reranker_provider

        if provider and provider not in self._reranker_clients:
            self._reranker_clients[provider] = RerankerClient(provider)

            # 记录状态
            self._update_model_status(f"reranker_{provider}", "reranker", provider)

        # 更新使用时间
        if provider:
            self._update_last_used(f"reranker_{provider}")

        return self._reranker_clients.get(provider) if provider else None

    def _update_model_status(self, model_key: str, model_type: str, provider: str) -> None:
        """更新模型状态

        Args:
            model_key: 模型键
            model_type: 模型类型
            provider: 提供商
        """
        if model_key not in self._model_status:
            self._model_status[model_key] = ModelStatus(
                name=model_key,
                type=model_type,
                provider=provider,
                initialized=True
            )

    def _update_last_used(self, model_key: str) -> None:
        """更新模型最后使用时间

        Args:
            model_key: 模型键
        """
        if model_key in self._model_status:
            self._model_status[model_key].last_used = datetime.now()

    def _record_error(self, model_key: str, error: str) -> None:
        """记录模型错误

        Args:
            model_key: 模型键
            error: 错误信息
        """
        if model_key in self._model_status:
            status = self._model_status[model_key]
            status.error_count += 1
            status.last_error = error

    def refresh_all_models(self) -> None:
        """刷新所有模型实例

        强制重新创建所有模型实例，用于配置变更后。
        """
        # 清除缓存
        self._llm_clients.clear()
        self._embedding_clients.clear()
        self._reranker_clients.clear()

        # 重新初始化
        self.initialize()

    def refresh_model(self, model_type: str, provider_name: Optional[str] = None) -> None:
        """刷新指定模型

        Args:
            model_type: 模型类型 ('llm', 'embedding', 'reranker')
            provider_name: 提供商名称
        """
        if model_type == "llm":
            provider = provider_name or self._settings.llm_provider
            if provider in self._llm_clients:
                self._llm_clients[provider].refresh_model()
        elif model_type == "embedding":
            provider = provider_name or self._settings.embedding_provider
            if provider in self._embedding_clients:
                self._embedding_clients[provider].refresh_embeddings()
        elif model_type == "reranker":
            provider = provider_name or self._settings.reranker_provider
            if provider and provider in self._reranker_clients:
                self._reranker_clients[provider].refresh_reranker()

    def get_model_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有模型状态

        Returns:
            模型状态字典
        """
        status_dict = {}

        for model_key, status in self._model_status.items():
            status_dict[model_key] = {
                "name": status.name,
                "type": status.type,
                "provider": status.provider,
                "initialized": status.initialized,
                "last_used": status.last_used.isoformat() if status.last_used else None,
                "error_count": status.error_count,
                "last_error": status.last_error,
            }

        return status_dict

    def test_all_connections(self) -> Dict[str, bool]:
        """测试所有模型连接

        Returns:
            连接测试结果字典
        """
        results = {}

        # 测试LLM
        try:
            results["llm"] = test_llm_connection()
        except Exception as e:
            results["llm"] = False
            self._record_error(f"llm_{self._settings.llm_provider}", str(e))

        # 测试嵌入
        try:
            results["embedding"] = test_embedding_connection()
        except Exception as e:
            results["embedding"] = False
            self._record_error(f"embedding_{self._settings.embedding_provider}", str(e))

        # 测试重排序（如果可用）
        if is_reranker_available():
            try:
                results["reranker"] = test_reranker_connection()
            except Exception as e:
                results["reranker"] = False
                if self._settings.reranker_provider:
                    self._record_error(f"reranker_{self._settings.reranker_provider}", str(e))
        else:
            results["reranker"] = None  # 未配置

        return results

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型配置信息

        Returns:
            模型信息字典
        """
        return {
            "llm": {
                "default_provider": self._settings.llm_provider,
                "available_providers": list(self._settings.llm_providers.keys()),
            },
            "embedding": {
                "default_provider": self._settings.embedding_provider,
                "available_providers": list(self._settings.embedding_providers.keys()),
                "dimension": self.get_embedding_dimension(),
            },
            "reranker": {
                "default_provider": self._settings.reranker_provider,
                "available_providers": list(self._settings.reranker_providers.keys()) if self._settings.reranker_providers else [],
                "available": is_reranker_available(),
            },
        }

    def get_embedding_dimension(self) -> int:
        """获取当前嵌入模型的维度

        Returns:
            向量维度
        """
        try:
            embedding_client = self.get_embedding_client()
            return embedding_client.get_dimension()
        except Exception:
            # 默认维度
            return 1024

    def embed_texts(self, texts: List[str], provider_name: Optional[str] = None) -> List[List[float]]:
        """批量嵌入文本

        Args:
            texts: 文本列表
            provider_name: 提供商名称

        Returns:
            嵌入向量列表
        """
        client = self.get_embedding_client(provider_name)
        return client.embed_texts(texts)

    def embed_query(self, text: str, provider_name: Optional[str] = None) -> List[float]:
        """嵌入查询文本

        Args:
            text: 查询文本
            provider_name: 提供商名称

        Returns:
            嵌入向量
        """
        client = self.get_embedding_client(provider_name)
        return client.embed_query(text)

    def rerank_documents(self, query: str, documents: List[str],
                        top_k: Optional[int] = None,
                        provider_name: Optional[str] = None) -> List[Tuple[str, float]]:
        """重排序文档

        Args:
            query: 查询字符串
            documents: 文档列表
            top_k: 返回前K个结果
            provider_name: 提供商名称

        Returns:
            重排序后的文档和得分列表
        """
        client = self.get_reranker_client(provider_name)
        if client:
            return client.rerank(query, documents, top_k)
        else:
            # 如果没有重排序，返回原始顺序
            results = [(doc, 1.0) for doc in documents]
            if top_k:
                results = results[:top_k]
            return results

    def cleanup(self) -> None:
        """清理资源

        释放模型缓存，清理资源。
        """
        self._llm_clients.clear()
        self._embedding_clients.clear()
        self._reranker_clients.clear()
        self._model_status.clear()
        self._initialized = False


# 全局模型管理器实例
_model_manager_instance: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """获取全局模型管理器实例"""
    global _model_manager_instance
    if _model_manager_instance is None:
        _model_manager_instance = ModelManager()
    return _model_manager_instance


def initialize_models() -> bool:
    """初始化所有模型

    Returns:
        初始化是否成功
    """
    manager = get_model_manager()
    return manager.initialize()


def get_llm_client(provider_name: Optional[str] = None) -> LLMClient:
    """获取LLM客户端

    Args:
        provider_name: 提供商名称

    Returns:
        LLMClient实例
    """
    manager = get_model_manager()
    return manager.get_llm_client(provider_name)


def get_embedding_client(provider_name: Optional[str] = None) -> EmbeddingClient:
    """获取嵌入客户端

    Args:
        provider_name: 提供商名称

    Returns:
        EmbeddingClient实例
    """
    manager = get_model_manager()
    return manager.get_embedding_client(provider_name)


def get_reranker_client(provider_name: Optional[str] = None) -> RerankerClient:
    """获取重排序客户端

    Args:
        provider_name: 提供商名称

    Returns:
        RerankerClient实例或None
    """
    manager = get_model_manager()
    return manager.get_reranker_client(provider_name)


def embed_texts(texts: List[str], provider_name: Optional[str] = None) -> List[List[float]]:
    """批量嵌入文本

    Args:
        texts: 文本列表
        provider_name: 提供商名称

    Returns:
        嵌入向量列表
    """
    manager = get_model_manager()
    return manager.embed_texts(texts, provider_name)


def embed_query(text: str, provider_name: Optional[str] = None) -> List[float]:
    """嵌入查询文本

    Args:
        text: 查询文本
        provider_name: 提供商名称

    Returns:
        嵌入向量
    """
    manager = get_model_manager()
    return manager.embed_query(text, provider_name)


def rerank_documents(query: str, documents: List[str],
                    top_k: Optional[int] = None,
                    provider_name: Optional[str] = None) -> List[Tuple[str, float]]:
    """重排序文档

    Args:
        query: 查询字符串
        documents: 文档列表
        top_k: 返回前K个结果
        provider_name: 提供商名称

    Returns:
        重排序后的文档和得分列表
    """
    manager = get_model_manager()
    return manager.rerank_documents(query, documents, top_k, provider_name)


def test_model_connections() -> Dict[str, bool]:
    """测试所有模型连接

    Returns:
        连接测试结果字典
    """
    manager = get_model_manager()
    return manager.test_all_connections()


def get_model_status() -> Dict[str, Dict[str, Any]]:
    """获取模型状态

    Returns:
        模型状态字典
    """
    manager = get_model_manager()
    return manager.get_model_status()


def get_model_info() -> Dict[str, Any]:
    """获取模型配置信息

    Returns:
        模型信息字典
    """
    manager = get_model_manager()
    return manager.get_model_info()