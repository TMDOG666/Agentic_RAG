from __future__ import annotations

"""api.controllers.health_controller

健康检查接口。

用途：
- 用于部署探活（liveness/readiness）。
- 用于本地快速确认服务已启动。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """健康检查。

    Returns:
        dict: 固定返回 `{"status": "ok"}`。
    """
    return {"status": "ok"}
