from __future__ import annotations

"""api.controllers.retrieval_controller

统一检索入口。

定位：
- 将多种检索模式（keyword/vector/entity/relation/graph expansion 等）统一收敛到一个 endpoint：`POST /retrieval`。
- 由 `RetrievalRequest.mode` 控制具体调用哪条底层路径。

底层实现：
- 当前走 `grag.entrypoint.GRAG` facade，内部会创建 RetrievalManager 并调用对应 primitives。
"""

from fastapi import APIRouter

from api.schemas.retrieval import RetrievalRequest, RetrievalResponse
from api.services.retrieval_service import RetrievalService

router = APIRouter()


@router.post("")
def retrieve(payload: RetrievalRequest) -> RetrievalResponse:
    """执行一次检索。

    Args:
        payload: RetrievalRequest（包含 group_id/mode/query/top_k/...）。

    Returns:
        RetrievalResponse: 统一结构的 result dict。
    """
    svc = RetrievalService()
    return svc.retrieve(payload)
