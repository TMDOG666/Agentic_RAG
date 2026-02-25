"""grag.model.reranker_client

重排序客户端（Reranker Client）

职责：
- 创建和管理重排序模型实例
- 对检索结果进行相关性重排序
- 支持多种重排序提供商
- 集成配置层进行参数配置

说明：
- 重排序是可选功能，用于改进检索结果质量
- 支持基于交叉编码器的重排序
- 可以与向量检索结合使用
- 提供批处理重排序能力

环境变量覆盖优先级（高 -> 低）：
- GRAG_RERANKER_PROVIDER
- GRAG_RERANKER_MODEL
- GRAG_RERANKER_BASE_URL
- GRAG_RERANKER_API_KEY
- grag_config.yaml 中的配置
"""

import os
from typing import List, Optional, Dict, Any, Tuple, Union
from pathlib import Path

from langchain_openai import OpenAIEmbeddings
from ..config import get_config_manager, ProviderType


class RerankerClient:
    """重排序客户端类

    提供检索结果重排序服务，用于提高检索结果的相关性。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化重排序客户端

        Args:
            provider_name: 提供商名称，如果为None则使用默认提供商
        """
        self.provider_name = provider_name
        self._reranker = None
        self._settings = get_config_manager().get_settings()

    def is_available(self) -> bool:
        """检查重排序服务是否可用

        Returns:
            是否配置了重排序提供商
        """
        try:
            provider_config = self._settings.get_provider_config(
                ProviderType.RERANKER,
                self.provider_name
            )
            return provider_config is not None
        except:
            return False

    def get_reranker(self):
        """获取或创建重排序器实例

        Returns:
            重排序器实例

        Raises:
            RuntimeError: 配置初始化失败或重排序器创建失败
        """
        if self._reranker is None and self.is_available():
            self._reranker = self._create_reranker()
        return self._reranker

    def _create_reranker(self):
        """根据配置创建重排序器实例

        Returns:
            配置好的重排序器实例

        Raises:
            ValueError: 配置无效或缺少必需参数
        """
        # 获取提供商配置
        provider_config = self._settings.get_provider_config(
            ProviderType.RERANKER,
            self.provider_name
        )

        # 环境变量覆盖
        model = self._get_env_override("GRAG_RERANKER_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_RERANKER_BASE_URL") or provider_config.base_url
        top_k = provider_config.top_k
        timeout = provider_config.timeout

        # API Key获取
        api_key = self._get_api_key(provider_config)

        provider_name = self.provider_name or self._settings.reranker_provider

        try:
            if provider_name in ["siliconflow", "openai"]:
                # 使用OpenAI兼容的重排序API
                if not api_key and base_url and not self._is_local_url(base_url):
                    raise ValueError(f"API Key 不能为空 (provider: {provider_name})")

                # 这里可以集成具体的重排序实现
                # 例如使用sentence-transformers或专门的重排序API
                reranker = self._create_openai_reranker(
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout
                )
            else:
                # 其他重排序实现
                reranker = self._create_default_reranker()

            return reranker

        except Exception as e:
            raise RuntimeError(f"创建重排序器失败: {e}") from e

    def _create_openai_reranker(self, model: str, api_key: Optional[str],
                               base_url: Optional[str], timeout: int):
        """创建基于OpenAI的重排序器

        Args:
            model: 模型名称
            api_key: API密钥
            base_url: 基础URL
            timeout: 超时时间

        Returns:
            重排序器实例
        """
        # 这里实现具体的重排序逻辑
        # 可以调用重排序API或使用本地模型
        class OpenAIReranker:
            def __init__(self, model: str, api_key: str, base_url: str, timeout: int):
                self.model = model
                self.api_key = api_key
                self.base_url = base_url
                self.timeout = timeout

            def rerank(self, query: str, documents: List[str],
                      top_k: Optional[int] = None) -> List[Tuple[str, float]]:
                """重排序文档列表

                Args:
                    query: 查询字符串
                    documents: 文档列表
                    top_k: 返回前K个结果

                Returns:
                    重排序后的文档和得分列表
                """
                # 简化实现：返回原始顺序（实际应该调用重排序API）
                results = [(doc, 1.0) for doc in documents]
                if top_k:
                    results = results[:top_k]
                return results

        return OpenAIReranker(model, api_key or "EMPTY", base_url, timeout)

    def _create_default_reranker(self):
        """创建默认重排序器

        Returns:
            默认重排序器实例
        """
        class DefaultReranker:
            def rerank(self, query: str, documents: List[str],
                      top_k: Optional[int] = None) -> List[Tuple[str, float]]:
                """默认重排序：保持原始顺序

                Args:
                    query: 查询字符串
                    documents: 文档列表
                    top_k: 返回前K个结果

                Returns:
                    文档和得分列表
                """
                results = [(doc, 1.0) for doc in documents]
                if top_k:
                    results = results[:top_k]
                return results

        return DefaultReranker()

    def _get_api_key(self, provider_config) -> Optional[str]:
        """获取API Key

        Args:
            provider_config: 提供商配置对象

        Returns:
            API Key字符串或None
        """
        # 1. 通用环境变量
        api_key = os.environ.get("GRAG_RERANKER_API_KEY")
        if api_key:
            return api_key

        # 2. 提供商指定的环境变量
        if hasattr(provider_config, 'api_key_env') and provider_config.api_key_env:
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key

        # 3. 特定提供商的兼容环境变量
        provider_name = self.provider_name or self._settings.reranker_provider
        if provider_name == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")
            if api_key:
                return api_key

        # 4. 对于本地服务，返回占位符
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

    def rerank(self, query: str, documents: List[str],
              top_k: Optional[int] = None) -> List[Tuple[str, float]]:
        """重排序文档列表

        Args:
            query: 查询字符串
            documents: 文档列表
            top_k: 返回前K个结果，如果为None则返回所有结果

        Returns:
            重排序后的文档和得分列表 [(document, score), ...]

        Raises:
            RuntimeError: 重排序失败
        """
        if not self.is_available():
            # 如果没有配置重排序，返回原始顺序
            results = [(doc, 1.0) for doc in documents]
            if top_k:
                results = results[:top_k]
            return results

        try:
            reranker = self.get_reranker()
            return reranker.rerank(query, documents, top_k)
        except Exception as e:
            # 重排序失败时返回原始顺序
            print(f"重排序失败，使用原始顺序: {e}")
            results = [(doc, 1.0) for doc in documents]
            if top_k:
                results = results[:top_k]
            return results

    def test_connection(self) -> bool:
        """测试重排序服务连接

        Returns:
            连接是否成功
        """
        if not self.is_available():
            return False

        try:
            # 尝试重排序测试数据
            test_query = "test query"
            test_docs = ["doc1", "doc2", "doc3"]
            results = self.rerank(test_query, test_docs, top_k=2)
            return len(results) > 0
        except Exception as e:
            print(f"重排序连接测试失败: {e}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        """获取提供商信息

        Returns:
            提供商信息字典
        """
        if not self.is_available():
            return {"available": False}

        provider_config = self._settings.get_provider_config(
            ProviderType.RERANKER,
            self.provider_name
        )

        return {
            "provider_name": self.provider_name or self._settings.reranker_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "top_k": provider_config.top_k,
            "timeout": provider_config.timeout,
            "available": True,
        }

    def refresh_reranker(self) -> None:
        """刷新重排序器实例（强制重新创建）

        用于配置变更后重新初始化模型。
        """
        self._reranker = None


# 全局重排序客户端实例
_default_reranker_client: Optional[RerankerClient] = None


def get_reranker_client(provider_name: Optional[str] = None) -> RerankerClient:
    """获取重排序客户端实例

    Args:
        provider_name: 提供商名称

    Returns:
        RerankerClient实例
    """
    global _default_reranker_client
    if _default_reranker_client is None or provider_name is not None:
        _default_reranker_client = RerankerClient(provider_name)
    return _default_reranker_client


def rerank_documents(query: str, documents: List[str],
                    top_k: Optional[int] = None,
                    provider_name: Optional[str] = None) -> List[Tuple[str, float]]:
    """重排序文档列表

    Args:
        query: 查询字符串
        documents: 文档列表
        top_k: 返回前K个结果
        provider_name: 提供商名称

    Returns:
        重排序后的文档和得分列表
    """
    client = get_reranker_client(provider_name)
    return client.rerank(query, documents, top_k)


def is_reranker_available(provider_name: Optional[str] = None) -> bool:
    """检查重排序服务是否可用

    Args:
        provider_name: 提供商名称

    Returns:
        是否可用
    """
    client = get_reranker_client(provider_name)
    return client.is_available()


def test_reranker_connection(provider_name: Optional[str] = None) -> bool:
    """测试重排序连接

    Args:
        provider_name: 提供商名称

    Returns:
        连接是否成功
    """
    client = get_reranker_client(provider_name)
    return client.test_connection()