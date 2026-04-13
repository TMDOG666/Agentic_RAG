from __future__ import annotations

"""api.controllers.router

API 路由聚合器。

本文件集中负责：
- 导入各个 controller 的 `router`。
- 将它们按统一的 prefix/tag 注册到 `api_router`。

好处：
- `api.main` 只需要 include 一次 `api_router`。
- 新增/下线接口时只需要修改本文件即可。
"""

from fastapi import APIRouter

from api.controllers.agent_controller import router as agent_router
from api.controllers.documents_controller import router as documents_router
from api.controllers.entities_controller import router as entities_router
from api.controllers.groups_controller import router as groups_router
from api.controllers.groups_admin_controller import router as groups_admin_router
from api.controllers.health_controller import router as health_router
from api.controllers.ingest_controller import router as ingest_router
from api.controllers.ingest_tasks_controller import router as ingest_tasks_router
from api.controllers.logs_controller import router as logs_router
from api.controllers.retrieval_controller import router as retrieval_router
from api.controllers.skills_controller import router as skills_router

api_router = APIRouter()

# 说明：
# - `health_router` 自带了 `/health` 路径，因此这里不再额外加 prefix。
api_router.include_router(health_router, tags=["health"])

# group 相关：
# - `/groups`：查询类接口
# - `/groups-admin`：管理类接口（创建/删除 group 及级联清理）
api_router.include_router(groups_router, prefix="/groups", tags=["groups"])
api_router.include_router(groups_admin_router, prefix="/groups-admin", tags=["groups"])

# 资产/能力类：
# - entities: Postgres entities CRUD
# - documents: 文档元信息读取 + doc 级删除
# - ingest: 文档录入（文本/上传）
api_router.include_router(entities_router, prefix="/entities", tags=["entities"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(ingest_router, prefix="/ingest", tags=["ingest"])
api_router.include_router(ingest_tasks_router, prefix="/ingest-tasks", tags=["ingest"])
api_router.include_router(logs_router, prefix="/logs", tags=["system"])

# retrieval: 对 GRAG 检索能力的统一封装入口
api_router.include_router(retrieval_router, prefix="/retrieval", tags=["retrieval"])

# agent/skills: Agent 运行与 Skills 管理
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(skills_router, prefix="/skills", tags=["skills"])
