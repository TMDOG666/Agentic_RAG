"""adapter.runtime
 
 该模块属于 **接入层（Adapter Layer）**，负责把分层模块“组装”成一个可运行的 Agent Runtime。
 
 这里不实现具体业务逻辑（例如事件抽取），也不实现技能/工具本身；它只做依赖拼装：
 
 - Skill 层：`SkillManager`（发现/加载/执行技能）
 - Tool 层：`create_tools`（把 SkillManager 的能力暴露为函数调用工具）
 - LLM 接口层：`load_agent_config` + `create_model`（读取配置并创建模型实例）
 - 接入层工作流：`create_system_prompt` + `build_graph`（LangGraph 工作流）
 
 返回的 runtime 字典是 Agent 层入口（`agent.agent_with_skills`）唯一依赖的“组装产物”。
 
"""

import os
from pathlib import Path

from agent.adapter.graph import build_graph, create_system_prompt
from agent.llm.config import create_model, load_agent_config
from agent.skill.manager import SkillManager
from agent.tools.skill_tools import create_tools


def _resolve_agent_config_path() -> str:
    """解析 Agent 配置路径，优先使用环境变量，其次使用项目内标准配置位置。"""
    env_path = os.environ.get("AGENT_CONFIG")
    if env_path:
        return env_path

    candidates = [
        Path("config") / "agent_config.yaml",
        Path("agent_config.yaml"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def create_runtime():
    """创建并返回 Agent Runtime。

    Runtime 是一个包含以下对象的字典：

    - `skill_manager`: 技能管理器（扫描 `.cursor/skills`，按需加载/读文件/执行脚本）
    - `tools`: 提供给模型调用的 LangChain Tools
    - `agent_config`: 解析得到的配置（字典）
    - `model`: LangChain `ChatOpenAI`（或 OpenAI 兼容）模型对象
    - `system_prompt`: 系统提示词（包含技能列表与工具使用约束）
    - `graph`: LangGraph 编译后的可执行图（`.invoke` 驱动对话/工具）

    环境变量：
    - `AGENT_CONFIG`: 配置文件路径（默认 `agent_config.yaml`）

    Returns:
        dict: 组装完成的 runtime。
    """

    # Skill 层：扫描技能目录并建立索引（元数据）。
    skill_manager = SkillManager()

    # Tool 层：把 SkillManager 的能力包装为可被大模型 function-call 的工具。
    tools = create_tools(skill_manager)

    # LLM 接口层：读取配置并实例化模型。
    config_path = _resolve_agent_config_path()
    agent_config = load_agent_config(config_path)
    model = create_model(agent_config)

    # 接入层：系统提示词（包含技能列表、工具规则）+ LangGraph 工作流。
    system_prompt = create_system_prompt(skill_manager)
    graph = build_graph(model=model, tools=tools, system_prompt=system_prompt)

    # 统一返回，入口模块只从 runtime 中取依赖，不再散落 import 各层实现。
    return {
        "skill_manager": skill_manager,
        "tools": tools,
        "agent_config": agent_config,
        "model": model,
        "system_prompt": system_prompt,
        "graph": graph,
    }
