from __future__ import annotations

from pathlib import Path

from agent.llm.config import build_agent_runtime_snapshot
from grag.config import ConfigManager


def _write_grag_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "grag_config.yaml"
    config_path.write_text(
        """
llm_provider: siliconflow
embedding_provider: local_embed
reranker_provider: local_reranker
vision_provider: siliconflow
vector_db_provider: milvus
graph_db_provider: neo4j
relational_db_provider: postgres
llm_providers:
  siliconflow:
    model: sf-model
    base_url: https://sf.test/v1
    api_key_env: SILICONFLOW_API_KEY
  minimax:
    model: mm-model
    base_url: https://mm.test/v1
    api_key_env: MINIMAX_API_KEY
embedding_providers:
  local_embed:
    model: embed-model
    base_url: http://127.0.0.1:8008/v1
    api_key_env: EMBEDDING_API_KEY
    dimension: 1024
reranker_providers:
  local_reranker:
    model: reranker-model
    base_url: http://127.0.0.1:8010/v1
    api_key_env: RERANKER_API_KEY
    top_k: 10
vision_providers:
  siliconflow:
    model: vision-model
    base_url: https://sf.test/v1
    api_key_env: SILICONFLOW_API_KEY
vector_databases:
  milvus:
    host: localhost
    port: 19530
    collection_name: chunks
graph_databases:
  neo4j:
    uri: bolt://localhost:7687
    user: neo4j
    password_env: NEO4J_PASSWORD
relational_databases:
  postgres:
    host: localhost
    port: 5432
    database: grag
    user: postgres
    password_env: POSTGRES_PASSWORD
system:
  workspace_dir: ./data
preprocessing: {}
graph_construction:
  coreference_resolution:
    enabled: true
    model_provider: siliconflow
  entity_relation_extraction:
    enabled: true
    model_provider: siliconflow
  entity_resolution_knowledge_fusion:
    enabled: true
    fusion_llm_provider: minimax
retrieval: {}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def test_runtime_snapshot_honors_env_overrides(tmp_path, monkeypatch):
    _write_grag_config(Path(tmp_path))
    cm = ConfigManager(config_dir=tmp_path)
    assert cm.initialize() is True

    monkeypatch.setenv("GRAG_LLM_PROVIDER", "minimax")
    monkeypatch.setenv("GRAG_LLM_MODEL", "MiniMax-M2")
    monkeypatch.setenv("GRAG_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("GRAG_LLM_API_KEY", "test-key")

    snapshot = cm.get_runtime_snapshot()
    default_llm = snapshot["defaults"]["llm"]
    ingest_llm = snapshot["ingest"]["global_llm"]

    assert default_llm["provider_name"] == "minimax"
    assert default_llm["model"] == "MiniMax-M2"
    assert default_llm["base_url"] == "https://example.test/v1"
    assert default_llm["api_key_present"] is True
    assert default_llm["api_key_source"] == "GRAG_LLM_API_KEY"
    assert ingest_llm["provider_name"] == "minimax"


def test_agent_runtime_snapshot_honors_env_overrides(tmp_path, monkeypatch):
    config_path = Path(tmp_path) / "agent_config.yaml"
    config_path.write_text(
        """
provider: siliconflow
providers:
  siliconflow:
    model: default-model
    base_url: https://siliconflow.test/v1
    api_key_env: SILICONFLOW_API_KEY
    temperature: 0
  minimax:
    model: minimax-default
    base_url: https://minimax.test/v1
    api_key_env: MINIMAX_API_KEY
    temperature: 0.2
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENT_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("AGENT_BASE_URL", "https://agent-runtime.test/v1")
    monkeypatch.setenv("AGENT_API_KEY", "agent-key")
    monkeypatch.setenv("AGENT_TEMPERATURE", "0.35")

    snapshot = build_agent_runtime_snapshot(str(config_path))

    assert snapshot["provider_name"] == "minimax"
    assert snapshot["model"] == "MiniMax-M2.7"
    assert snapshot["base_url"] == "https://agent-runtime.test/v1"
    assert snapshot["temperature"] == 0.35
    assert snapshot["api_key_present"] is True
    assert snapshot["api_key_source"] == "AGENT_API_KEY"
