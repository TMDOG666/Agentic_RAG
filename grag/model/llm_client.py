"""统一的 LLM 客户端。"""

from __future__ import annotations

import ipaddress
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..config import ProviderType, get_config_manager


class LLMClient:
    """按当前配置创建并管理 LLM 模型实例。"""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = provider_name
        self._model: Optional[BaseChatModel] = None

    def _get_settings(self):
        return get_config_manager().get_settings()

    def get_model(self) -> BaseChatModel:
        if self._model is None:
            self._model = self._create_model()
        return self._model

    def _create_model(self) -> BaseChatModel:
        settings = self._get_settings()
        provider_config = settings.get_provider_config(ProviderType.LLM, self.provider_name)

        model = self._get_env_override("GRAG_LLM_MODEL") or provider_config.model
        base_url = self._get_env_override("GRAG_LLM_BASE_URL") or provider_config.base_url
        temperature = self._get_env_override_float("GRAG_LLM_TEMPERATURE")
        if temperature is None:
            temperature = provider_config.temperature
        max_tokens = provider_config.max_tokens
        timeout = provider_config.timeout
        api_key = self._get_api_key(provider_config)

        if not model:
            raise ValueError("LLM model 不能为空")
        if not api_key and base_url and not self._is_local_url(base_url):
            raise ValueError(f"API Key 不能为空 (provider: {self.provider_name or settings.llm_provider})")

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
            raise RuntimeError(f"创建 LLM 模型失败: {exc}") from exc

    def _get_api_key(self, provider_config) -> Optional[str]:
        api_key = os.environ.get("GRAG_LLM_API_KEY")
        if api_key:
            return api_key

        if getattr(provider_config, "api_key_env", None):
            api_key = os.environ.get(provider_config.api_key_env)
            if api_key:
                return api_key

        settings = self._get_settings()
        provider_name = self.provider_name or settings.llm_provider
        if provider_name == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")
            if api_key:
                return api_key

        if provider_config.base_url and self._is_local_url(provider_config.base_url):
            return "EMPTY"
        return None

    @staticmethod
    def _get_env_override(env_var: str) -> Optional[str]:
        return os.environ.get(env_var)

    @staticmethod
    def _get_env_override_float(env_var: str) -> Optional[float]:
        value = os.environ.get(env_var)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _is_local_url(url: str) -> bool:
        if not url:
            return False

        url_lower = url.lower()
        if any(indicator in url_lower for indicator in ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"]):
            return True

        try:
            host = (urlparse(url).hostname or "").strip()
            if not host:
                return False
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private
        except ValueError:
            return False

    def test_connection(self) -> bool:
        try:
            response = self.get_model().invoke([{"role": "user", "content": "Hello"}])
            return response is not None
        except Exception as exc:
            print(f"LLM 连接测试失败: {exc}")
            return False

    def get_provider_info(self) -> Dict[str, Any]:
        settings = self._get_settings()
        provider_config = settings.get_provider_config(ProviderType.LLM, self.provider_name)
        return {
            "provider_name": self.provider_name or settings.llm_provider,
            "model": provider_config.model,
            "base_url": provider_config.base_url,
            "temperature": provider_config.temperature,
            "max_tokens": provider_config.max_tokens,
            "timeout": provider_config.timeout,
        }

    def refresh_model(self) -> None:
        self._model = None

    def chat(self, text: str) -> str:
        model = self.get_model()
        try:
            response = model.invoke([{"role": "user", "content": text}])
        except Exception as exc:
            raise RuntimeError(self._format_chat_error(exc)) from exc

        if hasattr(response, "content"):
            return response.content
        return str(response)

    def _format_chat_error(self, exc: Exception) -> str:
        info = self.get_provider_info()
        parts = [
            "LLM 对话调用失败",
            f"provider={info.get('provider_name') or 'unknown'}",
            f"model={info.get('model') or 'unknown'}",
        ]

        base_url = str(info.get("base_url") or "").strip()
        if base_url:
            parts.append(f"base_url={base_url}")

        status_code = self._extract_status_code(exc)
        if status_code is not None:
            parts.append(f"status_code={status_code}")

        error_type = self._extract_exception_type(exc)
        if error_type:
            parts.append(f"error_type={error_type}")

        detail = self._extract_exception_detail(exc)
        if detail:
            parts.append(f"detail={detail}")

        chain = self._build_exception_chain(exc)
        if chain:
            parts.append(f"chain={chain}")
        return " | ".join(parts)

    @staticmethod
    def _extract_status_code(exc: Exception) -> Optional[int]:
        for candidate in [exc, getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]:
            if candidate is None:
                continue
            status_code = getattr(candidate, "status_code", None)
            if isinstance(status_code, int):
                return status_code
            response = getattr(candidate, "response", None)
            response_status = getattr(response, "status_code", None)
            if isinstance(response_status, int):
                return response_status
        return None

    @staticmethod
    def _extract_exception_type(exc: Exception) -> str:
        for candidate in [exc, getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]:
            if candidate is None:
                continue
            type_name = type(candidate).__name__
            if type_name:
                return type_name
        return ""

    @staticmethod
    def _extract_exception_detail(exc: Exception) -> str:
        for candidate in [exc, getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]:
            if candidate is None:
                continue
            response = getattr(candidate, "response", None)
            if response is not None:
                text = getattr(response, "text", None)
                if callable(text):
                    try:
                        text = text()
                    except Exception:
                        text = None
                if text:
                    return str(text).strip().replace("\r", " ").replace("\n", " ")[:1000]
            body = getattr(candidate, "body", None)
            if body:
                return str(body).strip().replace("\r", " ").replace("\n", " ")[:1000]
            message = str(candidate or "").strip()
            if message:
                return message.replace("\r", " ").replace("\n", " ")[:1000]
        return ""

    @staticmethod
    def _build_exception_chain(exc: Exception) -> str:
        seen = set()
        parts = []
        current = exc
        while current is not None and id(current) not in seen and len(parts) < 5:
            seen.add(id(current))
            text = str(current or "").strip()
            if text:
                parts.append(f"{type(current).__name__}: {text}")
            current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        return " <- ".join(parts)


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
