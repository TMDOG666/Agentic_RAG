from __future__ import annotations

"""Agent API：对话执行相关接口。"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.schemas.agent import AgentRunIn, AgentRunOut
from api.services.agent_service import AgentService

router = APIRouter()


@router.post("/run")
def run_agent(payload: AgentRunIn) -> AgentRunOut:
    svc = AgentService()
    return svc.run(payload)


@router.post("/stream")
def stream_agent(payload: AgentRunIn) -> StreamingResponse:
    svc = AgentService()
    return StreamingResponse(
        svc.stream(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
