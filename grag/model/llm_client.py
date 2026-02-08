"""grag.model.llm_client

LLM客户端（LLM Client）

职责：
- 创建和管理LLM模型实例
- 支持多种LLM提供商（OpenAI、硅基流动、vLLM、Ollama等）
- 处理模型调用的统一接口
- 集成配置层进行参数配置

说明：
- 统一使用OpenAI兼容接口（ChatOpenAI）
- 通过base_url区分不同提供商
- 支持环境变量覆盖配置参数
- 提供连接测试和错误处理

环境变量覆盖优先级（高 -> 低）：
- GRAG_LLM_PROVIDER
- GRAG_LLM_MODEL
- GRAG_LLM_BASE_URL
- GRAG_LLM_TEMPERATURE
- GRAG_LLM_API_KEY
- grag_config.yaml 中的配置
"""

import os
from typing import Optional, Dict, Any, Union
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from ..config import get_grag_settings, get_settings, ProviderType


class LLMClient:
    """LLM客户端类

    提供统一的LLM模型创建和管理接口，支持多种提供商的切换。
    """

    def __init__(self, provider_name: Optional[str] = None):
        """初始化LLM客户端

        Args:
            provider_name: 提供商名称，如果为None则使用默认提供商
        """
        self.provider_name = provider_name
        self._model: Optional[BaseChatModel] = None
        try:
            self._settings = get_grag_settings()
        except Exception:
            self._settings = get_settings()

    def get_model(self) -> BaseChatModel:
        """获取或创建LLM模型实例

        Returns:
            BaseChatModel: LangChain Chat模型实例

        Raises:
            RuntimeError: 配置初始化失败或模型创建失败
        """
        if self._model is None:
            self._model = self._create_model()
        return self._model

    def _create_model(self) -> BaseChatModel:
        """根据配置创建LLM模型实例

        Returns:
            BaseChatModel: 配置好的模型实例

        Raises:
            ValueError: 配置无效或缺少必需参数
        """
        # 获取提供商配置
        provider_config = self._settings.get_provider_config(
            ProviderType.LLM,
            self.provider_name
        )

        # 环境变量覆盖
        model = self._get_env_override("GRAG_LLM_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_LLM_BASE_URL") or provider_config.base_url
        temperature = self._get_env_override_float("GRAG_LLM_TEMPERATURE") or provider_config.temperature
        max_tokens = provider_config.max_tokens
        timeout = provider_config.timeout

        # API Key获取（支持多种方式）
        api_key = self._get_api_key(provider_config)

        # 验证必需参数
        if not model:
            raise ValueError("LLM model 不能为空")
        if not api_key and base_url and not self._is_local_url(base_url):
            raise ValueError(f"API Key 不能为空 (provider: {self.provider_name or self._settings.llm_provider})")

        try:
            # 创建ChatOpenAI实例
            model_instance = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                api_key=api_key,
                base_url=base_url,
            )

            return model_instance

        except Exception as e:
            raise RuntimeError(f"创建LLM模型失败: {e}") from e

    def _get_api_key(self, provider_config) -> Optional[str]:
        """获取API Key

        优先级：
        1. 环境变量 GRAG_LLM_API_KEY
        2. 提供商配置中的环境变量
        3. 特定提供商的兼容环境变量

        Args:
            provider_config: 提供商配置对象

        Returns:
            API Key字符串或None
        """
        # 1. 通用环境变量
        api_key = os.environ.get("GRAG_LLM_API_KEY")
        if api_key:
            return api_key

        # 2. 提供商指定的环境变量
        if hasattr(provider_config, 'api_key_env') and provider_config.api_key_env:
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key

        # 3. 特定提供商的兼容环境变量
        provider_name = self.provider_name or self._settings.llm_provider
        if provider_name == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")
            if api_key:
                return api_key

        # 4. 对于本地服务，返回占位符
        if provider_config.base_url and self._is_local_url(provider_config.base_url):
            return "EMPTY"  # 本地服务可能不需要API Key

        return None

    def _get_env_override(self, env_var: str) -> Optional[str]:
        """获取环境变量覆盖值

        Args:
            env_var: 环境变量名

        Returns:
            环境变量值或None
        """
        return os.environ.get(env_var)

    def _get_env_override_float(self, env_var: str) -> Optional[float]:
        """获取环境变量覆盖值（浮点数）

        Args:
            env_var: 环境变量名

        Returns:
            浮点数值或None
        """
        value = os.environ.get(env_var)
        if value is not None:
            try:
                return float(value)
            except ValueError:
                return None
        return None

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

    def test_connection(self) -> bool:
        """测试模型连接

        Returns:
            连接是否成功
        """
        try:
            model = self.get_model()
            # 发送一个简单的测试请求
            response = model.invoke([{"role": "user", "content": "Hello"}])
            return response is not None
        except Exception as e:
            print(f"LLM连接测试失败: {e}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        """获取提供商信息

        Returns:
            提供商信息字典
        """
        provider_config = self._settings.get_provider_config(
            ProviderType.LLM,
            self.provider_name
        )

        return {
            "provider_name": self.provider_name or self._settings.llm_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "temperature": provider_config.temperature,
            "max_tokens": provider_config.max_tokens,
            "timeout": provider_config.timeout,
        }

    def refresh_model(self) -> None:
        """刷新模型实例（强制重新创建）

        用于配置变更后重新初始化模型。
        """
        self._model = None

    def chat(self, text: str) -> str:
        """使用当前 LLM 进行一次简单对话（单轮、纯文本）。

        主要用于诸如文档标准化这类“给定一段文本，让模型直接返回整理结果”的场景。

        Args:
            text: 传给模型的完整提示词/文本。

        Returns:
            模型返回的文本内容（如果响应对象有 content 字段，则优先使用）。
        """
        model = self.get_model()
        try:
            response = model.invoke([{"role": "user", "content": text}])
        except Exception as e:
            # 让上层决定如何处理异常（预处理里会捕获并回退到原始内容）
            raise RuntimeError(f"LLM 对话调用失败: {e}") from e

        # LangChain ChatOpenAI 通常返回带 .content 的消息对象
        if hasattr(response, "content"):
            return response.content
        return str(response)


# 全局LLM客户端实例
_default_llm_client: Optional[LLMClient] = None


def get_llm_client(provider_name: Optional[str] = None) -> LLMClient:
    """获取LLM客户端实例

    Args:
        provider_name: 提供商名称

    Returns:
        LLMClient实例
    """
    global _default_llm_client
    if _default_llm_client is None or provider_name is not None:
        _default_llm_client = LLMClient(provider_name)
    return _default_llm_client


def get_llm_model(provider_name: Optional[str] = None) -> BaseChatModel:
    """获取LLM模型实例

    Args:
        provider_name: 提供商名称

    Returns:
        LangChain Chat模型实例
    """
    client = get_llm_client(provider_name)
    return client.get_model()


def test_llm_connection(provider_name: Optional[str] = None) -> bool:
    """测试LLM连接

    Args:
        provider_name: 提供商名称

    Returns:
        连接是否成功
    """
    client = get_llm_client(provider_name)
    return client.test_connection()