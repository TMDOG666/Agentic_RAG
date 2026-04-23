from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..config import ProviderType
from .provider_client_base import ProviderClientBase


class LLMClient(ProviderClientBase):
    """统一的 LLM 客户端。"""

    def __init__(self, provider_name: Optional[str] = None):
        super().__init__(provider_name=provider_name)
        self._model: Optional[BaseChatModel] = None

    def get_model(self) -> BaseChatModel:
        if self._model is None:
            self._model = self._create_model()
        return self._model

    def _create_model(self) -> BaseChatModel:
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.LLM)
        provider_name = self.provider_name or settings.llm_provider
        model = self._get_env_override("GRAG_LLM_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_LLM_BASE_URL") or provider_config.base_url
        temperature = self._get_env_override_float("GRAG_LLM_TEMPERATURE")
        if temperature is None:
            temperature = provider_config.temperature
        max_tokens = provider_config.max_tokens
        timeout = provider_config.timeout
        api_key = self._resolve_api_key(
            provider_config=provider_config,
            provider_name=provider_name,
            env_override_name="GRAG_LLM_API_KEY",
            legacy_env_map={"siliconflow": "SILICONFLOW_API_KEY"},
        )

        if not model:
            raise ValueError("LLM model 不能为空")
        if not api_key and base_url and not self._is_local_url(base_url):
            raise ValueError(f"API Key 不能为空 (provider: {provider_name})")

        try:
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as exc:
            raise RuntimeError(
                self._format_provider_error(
                    operation="创建 LLM 模型失败",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            ) from exc

    def test_connection(self) -> bool:
        try:
            response = self.get_model().invoke([{"role": "user", "content": "Hello"}])
            return response is not None
        except Exception as exc:
            print(f"LLM 连接测试失败: {exc}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        settings = self._get_settings()
        provider_config = self._get_provider_config(ProviderType.LLM)
        return self._build_provider_info(
            provider_name=self.provider_name or settings.llm_provider,
            provider_config=provider_config,
            extra={
                "temperature": provider_config.temperature,
                "max_tokens": provider_config.max_tokens,
            },
        )

    def refresh_model(self) -> None:
        self._model = None

    def chat(self, text: str) -> str:
        try:
            response = self.get_model().invoke([{"role": "user", "content": text}])
        except Exception as exc:
            raise RuntimeError(
                self._format_provider_error(
                    operation="LLM 对话调用失败",
                    exc=exc,
                    provider_info=self.get_provider_info(),
                )
            ) from exc
        if hasattr(response, "content"):
            return response.content
        return str(response)


_default_llm_client: Optional[LLMClient] = None


def get_llm_client(provider_name: Optional[str] = None) -> LLMClient:
    global _default_llm_client
    if _default_llm_client is None or provider_name is not None:
        _default_llm_client = LLMClient(provider_name)
    return _default_llm_client


def get_llm_model(provider_name: Optional[str] = None) -> BaseChatModel:
    return get_llm_client(provider_name).get_model()


def test_llm_connection(provider_name: Optional[str] = None) -> bool:
    return get_llm_client(provider_name).test_connection()
