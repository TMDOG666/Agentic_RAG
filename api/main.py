from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.skill.manager import SkillManager
from agent.llm.config import load_agent_config
from api.controllers.router import api_router
from grag.config import ProviderType, get_config_manager
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
            agent_config = load_agent_config(_resolve_agent_config_path())
            agent_provider_name = str(
                os.environ.get("AGENT_PROVIDER") or agent_config.get("provider") or ""
            ).strip()
            agent_provider_config = (agent_config.get("providers") or {}).get(agent_provider_name) or {}
            agent_model = str(
                os.environ.get("AGENT_MODEL") or agent_provider_config.get("model") or ""
            ).strip()
            logger.info(
                "Agent provider: %s%s",
                agent_provider_name or "unknown",
                f" (model={agent_model})" if agent_model else "",
            )
        except Exception as exc:
            logger.warning("Failed to read agent provider on startup: %s: %s", type(exc).__name__, exc)

        try:
            cm = get_config_manager()
            settings = cm.get_settings()
            ingest_llm_provider_name = str(settings.llm_provider or "").strip()
            ingest_llm_provider_config = cm.get_provider_config(ProviderType.LLM, ingest_llm_provider_name)
            ingest_llm_model = str(getattr(ingest_llm_provider_config, "model", "") or "").strip()
            ingest_stage_providers = settings.resolve_graph_construction_llm_providers()
            logger.info(
                "Ingest LLM provider: %s%s",
                ingest_llm_provider_name or "unknown",
                f" (model={ingest_llm_model})" if ingest_llm_model else "",
            )
            logger.info(
                "Ingest stage LLM providers: coref=%s, extraction=%s, fusion=%s, entity_alignment=%s",
                ingest_stage_providers.get("coreference_resolution", "unknown"),
                ingest_stage_providers.get("entity_relation_extraction", "unknown"),
                ingest_stage_providers.get("fusion", "unknown"),
                ingest_stage_providers.get("entity_alignment", "unknown"),
            )
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
