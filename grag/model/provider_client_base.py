from __future__ import annotations

import ipaddress
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..config import ProviderType, get_config_manager


class ProviderClientBase:
    """共享 provider 配置读取与错误格式化逻辑。"""

    def __init__(self, provider_name: Optional[str] = None) -> None:
        self.provider_name = provider_name

    @staticmethod
    def _get_settings():
        return get_config_manager().get_settings()

    def _get_provider_config(self, provider_type: ProviderType):
        return self._get_settings().get_provider_config(provider_type, self.provider_name)

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

    def _resolve_api_key(
        self,
        *,
        provider_config,
        provider_name: str,
        env_override_name: str,
        legacy_env_map: Optional[Dict[str, str]] = None,
        allow_empty_for_local: bool = True,
    ) -> Optional[str]:
        api_key = os.environ.get(env_override_name)
        if api_key:
            return api_key
        api_key_env = getattr(provider_config, "api_key_env", None)
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if api_key:
                return api_key
        if legacy_env_map and provider_name in legacy_env_map:
            api_key = os.environ.get(legacy_env_map[provider_name])
            if api_key:
                return api_key
        if allow_empty_for_local and self._is_local_url(getattr(provider_config, "base_url", None) or ""):
            return "EMPTY"
        return None

    def _build_provider_info(self, *, provider_name: str, provider_config, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "provider_name": provider_name,
            "model": getattr(provider_config, "model", None),
            "base_url": getattr(provider_config, "base_url", None),
            "timeout": getattr(provider_config, "timeout", None),
        }
        if extra:
            info.update(extra)
        return info

    def _format_provider_error(self, *, operation: str, exc: Exception, provider_info: Dict[str, Any]) -> str:
        parts = [
            operation,
            f"provider={provider_info.get('provider_name') or 'unknown'}",
        ]
        model = str(provider_info.get("model") or "").strip()
        if model:
            parts.append(f"model={model}")
        base_url = str(provider_info.get("base_url") or "").strip()
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
