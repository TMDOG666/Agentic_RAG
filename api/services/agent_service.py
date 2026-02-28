from __future__ import annotations

"""api.services.agent_service

AgentService：对项目内 Agent 能力的 API 侧封装。

定位：
- controller 层只负责参数接收与返回模型。
- service 层负责调用底层 `agent` 包（例如带 skills 的 agent）并将结果转为 API schema。

注意：
- 当前实现为“同步一次性调用”（run_once）。
- 如果后续要支持流式输出/多轮会话，需要在这里扩展为 session-aware 的接口。
"""

from agent.agent.agent_with_skills import run_once

from api.schemas.agent import AgentRunIn, AgentRunOut


class AgentService:
    def run(self, payload: AgentRunIn) -> AgentRunOut:
        """运行一次 agent。

        Args:
            payload: API 入参（user_text + 可选 prefix）。

        Returns:
            AgentRunOut: agent 的输出文本。
        """
        # user_text 是用户输入；prefix 可用于在 API 层注入额外上下文（例如 system 指令/业务约束）。
        text = payload.user_text
        if payload.prefix:
            text = f"{payload.prefix}\n{text}"

        # run_once 会返回 agent 的最终答复；此处强转为 str，保证 schema 稳定。
        reply = run_once(text)
        return AgentRunOut(reply=str(reply))
