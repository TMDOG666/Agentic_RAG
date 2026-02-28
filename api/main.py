from __future__ import annotations

"""api.main

FastAPI 应用入口。

本模块职责：
- 构建 FastAPI `app` 实例（供 `uvicorn api.main:app` 启动）。
- 挂载 CORS 中间件（开发期默认放开，便于前端联调）。
- 挂载 API 总路由（见 `api.controllers.router.api_router`）。

注意：
- 该模块只负责 Web 层启动，不负责初始化数据库连接；底层组件由各 Service 懒加载。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.controllers.router import api_router


def create_app() -> FastAPI:
    """创建 FastAPI 应用。

    Returns:
        FastAPI: 可直接被 uvicorn 引用启动的应用实例。
    """
    app = FastAPI(title="Agentic_RAG API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        # 开发期默认允许所有来源；如果要上生产，建议收敛 allow_origins。
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载所有 API 子路由（controllers/router.py 中统一注册）。
    app.include_router(api_router)
    return app


app = create_app()
