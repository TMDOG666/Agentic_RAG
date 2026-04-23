from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.skill.manager import SkillManager
from agent.llm.config import build_agent_runtime_snapshot
from api.controllers.router import api_router
from grag.config import get_config_manager
from grag.graph_construction.async_graph_service import AsyncGraphBuildService


logger = logging.getLogger(__name__)


def _resolve_agent_config_path() -> str:
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


def create_app() -> FastAPI:
    app = FastAPI(title="Agentic_RAG API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.on_event("startup")
    def _startup() -> None:
        SkillManager()
        async_graph = AsyncGraphBuildService.instance()
        try:
            snapshot = build_agent_runtime_snapshot(_resolve_agent_config_path())
            logger.info(
                "Agent runtime config: provider=%s model=%s base_url=%s api_key=%s api_key_source=%s source=%s",
                snapshot.get("provider_name") or "unknown",
                snapshot.get("model") or "unknown",
                snapshot.get("base_url") or "-",
                "yes" if snapshot.get("api_key_present") else "no",
                snapshot.get("api_key_source") or "-",
                snapshot.get("config_source") or "config",
            )
        except Exception as exc:
            logger.warning("Failed to read agent provider on startup: %s: %s", type(exc).__name__, exc)

        try:
            cm = get_config_manager()
            for line in cm.format_runtime_snapshot_lines():
                logger.info("GRAG runtime config: %s", line)
        except Exception as exc:
            logger.warning("Failed to read ingest LLM provider on startup: %s: %s", type(exc).__name__, exc)

        try:
            cm = get_config_manager()
            settings = cm.get_settings()
            vision_provider_name = str(settings.vision_provider or "").strip()
            vision_provider_config = cm.get_provider_config(ProviderType.VISION, vision_provider_name)
            vision_model = str(getattr(vision_provider_config, "model", "") or "").strip()
            logger.info(
                "Vision provider: %s%s",
                vision_provider_name or "unknown",
                f" (model={vision_model})" if vision_model else "",
            )
        except Exception as exc:
            logger.warning("Failed to read vision provider on startup: %s: %s", type(exc).__name__, exc)

        try:
            recovered = async_graph.resume_incomplete_tasks()
            logger.info("Recovered ingest tasks on startup: %s", recovered)
        except Exception as exc:
            logger.warning("Failed to recover ingest tasks on startup: %s: %s", type(exc).__name__, exc)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        try:
            AsyncGraphBuildService.instance().shutdown()
        except Exception as exc:
            logger.warning("Failed to shutdown ingest task executor cleanly: %s: %s", type(exc).__name__, exc)

    return app


app = create_app()
