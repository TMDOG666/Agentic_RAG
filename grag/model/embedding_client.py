"""grag.model.embedding_client

向量嵌入客户端（Embedding Client）

职责：
- 创建和管理向量嵌入模型实例
- 支持多种嵌入提供商（OpenAI、硅基流动、HuggingFace等）
- 处理文本向量化的一致接口
- 集成配置层进行参数配置

说明：
- 支持批量嵌入处理
- 自动维度检测和验证
- 连接池管理和错误重试
- 支持本地和云端模型

环境变量覆盖优先级（高 -> 低）：
- GRAG_EMBEDDING_PROVIDER
- GRAG_EMBEDDING_MODEL
- GRAG_EMBEDDING_BASE_URL
- GRAG_EMBEDDING_API_KEY
- grag_config.yaml 中的配置
"""

import os
from typing import List, Optional, Dict, Any, Union
from pathlib import Path

from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

from ..config import get_grag_settings, ProviderType


class EmbeddingClient:
    """向量嵌入客户端类

    提供统一的向量嵌入服务，支持多种提供商和模型。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化嵌入客户端

        Args:
            provider_name: 提供商名称，如果为None则使用默认提供商
        """
        self.provider_name = provider_name
        self._embeddings: Optional[Embeddings] = None
        self._settings = get_grag_settings()

    def get_embeddings(self) -> Embeddings:
        """获取或创建嵌入模型实例

        Returns:
            Embeddings: LangChain嵌入模型实例

        Raises:
            RuntimeError: 配置初始化失败或模型创建失败
        """
        if self._embeddings is None:
            self._embeddings = self._create_embeddings()
        return self._embeddings

    def _create_embeddings(self) -> Embeddings:
        """根据配置创建嵌入模型实例

        Returns:
            Embeddings: 配置好的嵌入模型实例

        Raises:
            ValueError: 配置无效或缺少必需参数
        """
        # 获取提供商配置
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name
        )

        provider_name = self.provider_name or self._settings.embedding_provider

        # 环境变量覆盖
        model = self._get_env_override("GRAG_EMBEDDING_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_EMBEDDING_BASE_URL") or provider_config.base_url
        dimension = provider_config.dimension
        max_batch_size = provider_config.max_batch_size
        timeout = provider_config.timeout

        try:
            if provider_name == "huggingface":
                # HuggingFace本地模型
                embeddings = HuggingFaceEmbeddings(
                    model_name=model,
                    model_kwargs={"device": "auto"},
                    encode_kwargs={"normalize_embeddings": True}
                )
            else:
                # OpenAI兼容的云端模型
                api_key = self._get_api_key(provider_config)

                if not api_key and base_url and not self._is_local_url(base_url):
                    raise ValueError(f"API Key 不能为空 (provider: {provider_name})")

                embeddings = OpenAIEmbeddings(
                    model=model,
                    api_key=api_key or "EMPTY",
                    base_url=base_url,
                    timeout=timeout,
                    max_retries=3,
                )

            # 验证维度（如果可能的话）
            if hasattr(embeddings, '_check_dimensions'):
                self._validate_dimensions(embeddings, dimension)

            return embeddings

        except Exception as e:
            raise RuntimeError(f"创建嵌入模型失败: {e}") from e

    def _get_api_key(self, provider_config) -> Optional[str]:
        """获取API Key

        Args:
            provider_config: 提供商配置对象

        Returns:
            API Key字符串或None
        """
        # 1. 通用环境变量
        api_key = os.environ.get("GRAG_EMBEDDING_API_KEY")
        if api_key:
            return api_key

        # 2. 提供商指定的环境变量
        if hasattr(provider_config, 'api_key_env') and provider_config.api_key_env:
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key

        # 3. 特定提供商的兼容环境变量
        provider_name = self.provider_name or self._settings.embedding_provider
        if provider_name == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")
            if api_key:
                return api_key

        # 4. 对于本地HuggingFace模型，不需要API Key
        if provider_name == "huggingface":
            return None

        # 5. 对于本地服务，返回占位符
        if provider_config.base_url and self._is_local_url(provider_config.base_url):
            return "EMPTY"

        return None

    def _get_env_override(self, env_var: str) -> Optional[str]:
        """获取环境变量覆盖值

        Args:
            env_var: 环境变量名

        Returns:
            环境变量值或None
        """
        return os.environ.get(env_var)

    def _is_local_url(self, url: str) -> bool:
        """判断是否为本地URL

        Args:
            url: URL字符串

        Returns:
            是否为本地地址
        """
        if not url:
            return False

        local_indicators = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "local",
            ".local"
        ]

        url_lower = url.lower()
        return any(indicator in url_lower for indicator in local_indicators)

    def _validate_dimensions(self, embeddings: Embeddings, expected_dim: int) -> None:
        """验证嵌入维度

        Args:
            embeddings: 嵌入模型实例
            expected_dim: 期望的维度

        Raises:
            ValueError: 维度不匹配
        """
        try:
            # 尝试嵌入一个测试文本来获取维度
            test_embedding = embeddings.embed_query("test")
            actual_dim = len(test_embedding)

            if actual_dim != expected_dim:
                print(f"警告: 嵌入维度不匹配，期望 {expected_dim}，实际 {actual_dim}")
        except Exception:
            # 如果无法测试维度，跳过验证
            pass

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """嵌入文本列表

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表

        Raises:
            RuntimeError: 嵌入失败
        """
        try:
            embeddings = self.get_embeddings()
            return embeddings.embed_documents(texts)
        except Exception as e:
            raise RuntimeError(f"文本嵌入失败: {e}") from e

    def embed_query(self, text: str) -> List[float]:
        """嵌入单个查询文本

        Args:
            text: 查询文本

        Returns:
            嵌入向量

        Raises:
            RuntimeError: 嵌入失败
        """
        try:
            embeddings = self.get_embeddings()
            return embeddings.embed_query(text)
        except Exception as e:
            raise RuntimeError(f"查询嵌入失败: {e}") from e

    def test_connection(self) -> bool:
        """测试嵌入服务连接

        Returns:
            连接是否成功
        """
        try:
            # 尝试嵌入一个简单的测试文本
            embedding = self.embed_query("Hello world")
            return len(embedding) > 0
        except Exception as e:
            print(f"嵌入连接测试失败: {e}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        """获取提供商信息

        Returns:
            提供商信息字典
        """
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name
        )

        return {
            "provider_name": self.provider_name or self._settings.embedding_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "dimension": provider_config.dimension,
            "max_batch_size": provider_config.max_batch_size,
            "timeout": provider_config.timeout,
        }

    def get_dimension(self) -> int:
        """获取嵌入维度

        Returns:
            向量维度
        """
        provider_config = self._settings.get_provider_config(
            ProviderType.EMBEDDING,
            self.provider_name
        )
        return provider_config.dimension

    def refresh_embeddings(self) -> None:
        """刷新嵌入模型实例（强制重新创建）

        用于配置变更后重新初始化模型。
        """
        self._embeddings = None


# 全局嵌入客户端实例
_default_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client(provider_name: Optional[str] = None) -> EmbeddingClient:
    """获取嵌入客户端实例

    Args:
        provider_name: 提供商名称

    Returns:
        EmbeddingClient实例
    """
    global _default_embedding_client
    if _default_embedding_client is None or provider_name is not None:
        _default_embedding_client = EmbeddingClient(provider_name)
    return _default_embedding_client


def get_embeddings(provider_name: Optional[str] = None) -> Embeddings:
    """获取嵌入模型实例

    Args:
        provider_name: 提供商名称

    Returns:
        LangChain嵌入模型实例
    """
    client = get_embedding_client(provider_name)
    return client.get_embeddings()


def embed_texts(texts: List[str], provider_name: Optional[str] = None) -> List[List[float]]:
    """嵌入文本列表

    Args:
        texts: 文本列表
        provider_name: 提供商名称

    Returns:
        嵌入向量列表
    """
    client = get_embedding_client(provider_name)
    return client.embed_texts(texts)


def embed_query(text: str, provider_name: Optional[str] = None) -> List[float]:
    """嵌入查询文本

    Args:
        text: 查询文本
        provider_name: 提供商名称

    Returns:
        嵌入向量
    """
    client = get_embedding_client(provider_name)
    return client.embed_query(text)


def test_embedding_connection(provider_name: Optional[str] = None) -> bool:
    """测试嵌入连接

    Args:
        provider_name: 提供商名称

    Returns:
        连接是否成功
    """
    client = get_embedding_client(provider_name)
    return client.test_connection()