"""llm.config
 
 LLM 接口层（LLM Interface Layer）。
 
 职责：
 - 从 YAML 配置文件加载 Agent/LLM 配置（多 provider）
 - 根据配置与环境变量覆盖规则创建 LangChain 模型对象（OpenAI 兼容接口）
 
 约定：
 - 使用 `langchain_openai.ChatOpenAI` 作为统一的 OpenAI-Compatible 客户端
 - 通过 `base_url` 指向不同厂商/本地服务（vLLM/Ollama/LM Studio 等）
 
 环境变量覆盖优先级（高 -> 低）：
 - `AGENT_PROVIDER`
 - `AGENT_MODEL`
 - `AGENT_BASE_URL`
 - `AGENT_TEMPERATURE`
 - `AGENT_API_KEY`
 - provider 配置中的 `api_key_env`
 - 兼容：`SILICONFLOW_API_KEY` / `SILICONFLOW_BASE_URL`
 """
 
import os
from pathlib import Path
 
import yaml
from langchain_openai import ChatOpenAI


def load_agent_config(config_path: str = "agent_config.yaml") -> dict:
    """加载 Agent 配置。
 
     如果配置文件不存在，则返回一个内置默认配置（以 siliconflow 为默认 provider）。
 
     Args:
         config_path: 配置文件路径。
 
     Returns:
         dict: 配置字典。
     """
    path = Path(config_path)
    if not path.exists():
        # 提供一个可运行的最小默认配置，避免“无配置即崩溃”。
        return {
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

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def create_model(config: dict) -> ChatOpenAI:
    """根据配置与环境变量创建模型对象。
 
     说明：
 - 本项目统一走 OpenAI-Compatible 协议，因此用 `ChatOpenAI` 作为客户端
 - `provider` 只是“选择哪组配置”的逻辑概念，最终由 `base_url` 决定请求发往何处
 
 Args:
     config: `load_agent_config()` 返回的配置字典。
 
 Returns:
     ChatOpenAI: 可直接 `.invoke()` 的 LangChain Chat 模型实例。
     """
    # provider 的选择优先由环境变量覆盖，其次读取配置文件。
    provider = os.environ.get("AGENT_PROVIDER") or config.get("provider") or "siliconflow"
    providers = config.get("providers") or {}
    pconf = providers.get(provider) or {}

    # model/base_url/temperature 允许用环境变量覆盖。
    model = os.environ.get("AGENT_MODEL") or pconf.get("model")
    base_url = os.environ.get("AGENT_BASE_URL") or pconf.get("base_url")
    if not base_url and provider == "siliconflow":
        # 兼容旧环境变量命名。
        base_url = os.environ.get("SILICONFLOW_BASE_URL")

    temperature_raw = os.environ.get("AGENT_TEMPERATURE")
    temperature = float(temperature_raw) if temperature_raw is not None else float(pconf.get("temperature", 0))

    # API Key 的获取顺序：
    # 1) AGENT_API_KEY
    # 2) provider 配置中的 api_key_env 对应的环境变量
    # 3) siliconflow 兼容：SILICONFLOW_API_KEY
    api_key = os.environ.get("AGENT_API_KEY")
    if not api_key:
        api_key_env = pconf.get("api_key_env") or "OPENAI_API_KEY"
        api_key = os.environ.get(api_key_env)
        if not api_key and provider == "siliconflow":
            api_key = os.environ.get("SILICONFLOW_API_KEY")

    # 对部分本地服务，api_key 可能不校验。这里提供一个占位，避免 LangChain 构造失败。
    api_key = api_key or "EMPTY"

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
    )
