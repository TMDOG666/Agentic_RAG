"""Agent LLM 配置解析。

职责：
- 从 YAML 加载 Agent 配置；
- 统一解析环境变量覆盖优先级；
- 生成可打印的运行时配置快照；
- 基于最终生效配置构造 ChatOpenAI 模型。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_AGENT_CONFIG: dict[str, Any] = {
    "provider": "siliconflow",
    "providers": {
        "siliconflow": {
            "model": "Qwen/Qwen3-Next-80B-A3B-Instruct",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key_env": "SILICONFLOW_API_KEY",
            "temperature": 0,
        }
    },
}


def load_agent_config(config_path: str = "agent_config.yaml") -> dict[str, Any]:
    """加载 Agent 配置，不存在时返回最小可运行默认值。"""
    path = Path(config_path)
    if not path.exists():
        return dict(DEFAULT_AGENT_CONFIG)

    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return payload if isinstance(payload, dict) else {}


def _resolve_agent_provider_name(config: dict[str, Any]) -> str:
    provider = str(os.environ.get("AGENT_PROVIDER") or config.get("provider") or "siliconflow").strip()
    return provider or "siliconflow"


def resolve_agent_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """解析 Agent 运行时最终生效配置。

    覆盖优先级：
    1. `AGENT_*` 环境变量
    2. provider 配置中的字段
    3. siliconflow 历史兼容环境变量
    4. 内置兜底
    """

    providers = config.get("providers") or {}
    provider_name = _resolve_agent_provider_name(config)
    provider_config = providers.get(provider_name) or {}

    model = str(os.environ.get("AGENT_MODEL") or provider_config.get("model") or "").strip()
    base_url = str(os.environ.get("AGENT_BASE_URL") or provider_config.get("base_url") or "").strip()
    if not base_url and provider_name == "siliconflow":
        base_url = str(os.environ.get("SILICONFLOW_BASE_URL") or "").strip()

    temperature_raw = os.environ.get("AGENT_TEMPERATURE")
    if temperature_raw is not None:
        temperature = float(temperature_raw)
        temperature_source = "AGENT_TEMPERATURE"
    else:
        temperature = float(provider_config.get("temperature", 0))
        temperature_source = "config"

    api_key = str(os.environ.get("AGENT_API_KEY") or "").strip()
    api_key_source = "AGENT_API_KEY" if api_key else ""
    configured_api_key_env = str(provider_config.get("api_key_env") or "OPENAI_API_KEY").strip()
    if not api_key and configured_api_key_env:
        api_key = str(os.environ.get(configured_api_key_env) or "").strip()
        if api_key:
            api_key_source = configured_api_key_env
    if not api_key and provider_name == "siliconflow":
        api_key = str(os.environ.get("SILICONFLOW_API_KEY") or "").strip()
        if api_key:
            api_key_source = "SILICONFLOW_API_KEY"

    return {
        "provider_name": provider_name,
        "provider_source": "AGENT_PROVIDER" if os.environ.get("AGENT_PROVIDER") else "config",
        "model": model,
        "model_source": "AGENT_MODEL" if os.environ.get("AGENT_MODEL") else "config",
        "base_url": base_url,
        "base_url_source": (
            "AGENT_BASE_URL"
            if os.environ.get("AGENT_BASE_URL")
            else ("SILICONFLOW_BASE_URL" if provider_name == "siliconflow" and os.environ.get("SILICONFLOW_BASE_URL") else "config")
        ),
        "temperature": temperature,
        "temperature_source": temperature_source,
        "api_key": api_key or "EMPTY",
        "api_key_present": bool(api_key),
        "api_key_source": api_key_source,
        "configured_api_key_env": configured_api_key_env,
        "config_source": "env" if any(
            os.environ.get(name)
            for name in (
                "AGENT_PROVIDER",
                "AGENT_MODEL",
                "AGENT_BASE_URL",
                "AGENT_TEMPERATURE",
                "AGENT_API_KEY",
            )
        ) else "config",
        "provider_config": provider_config,
    }


def build_agent_runtime_snapshot(config_path: str = "agent_config.yaml") -> dict[str, Any]:
    """生成 Agent 配置快照，供启动日志与排障使用。"""
    config = load_agent_config(config_path)
    runtime = resolve_agent_runtime_config(config)
    return {
        "config_path": str(config_path),
        "provider_name": runtime["provider_name"],
        "provider_source": runtime["provider_source"],
        "model": runtime["model"],
        "model_source": runtime["model_source"],
        "base_url": runtime["base_url"],
        "base_url_source": runtime["base_url_source"],
        "temperature": runtime["temperature"],
        "temperature_source": runtime["temperature_source"],
        "api_key_present": runtime["api_key_present"],
        "api_key_source": runtime["api_key_source"],
        "config_source": runtime["config_source"],
    }


def create_model(config: dict[str, Any]):
    """根据最终生效的 Agent 配置构造模型实例。"""
    from langchain_openai import ChatOpenAI

    runtime = resolve_agent_runtime_config(config)
    return ChatOpenAI(
        model=runtime["model"],
        temperature=runtime["temperature"],
        api_key=runtime["api_key"],
        base_url=runtime["base_url"] or None,
    )
