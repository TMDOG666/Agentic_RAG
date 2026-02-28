from __future__ import annotations

"""api.controllers.agent_controller

Agent API（对话/执行）相关接口。

定位：
- 本 controller 只负责 HTTP 层的入参/出参。
- 实际 agent 执行逻辑在 `api.services.agent_service.AgentService`。

当前能力：
- 同步执行一次 `run_once`，返回最终 reply。
"""

from fastapi import APIRouter

from api.schemas.agent import AgentRunIn, AgentRunOut
from api.services.agent_service import AgentService

router = APIRouter()


@router.post("/run")
def run_agent(payload: AgentRunIn) -> AgentRunOut:
    """运行一次 agent，并返回回复。

    Args:
        payload: AgentRunIn（包含 user_text + 可选 prefix）。

    Returns:
        AgentRunOut: reply 文本。
    """
    svc = AgentService()
    return svc.run(payload)
