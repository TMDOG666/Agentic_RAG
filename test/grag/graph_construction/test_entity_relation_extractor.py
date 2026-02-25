from pathlib import Path

import asyncio
import json
import time

from grag.graph_construction.entity_relation_extractor import (
    Chunk,
    EntityRelationExtractor,
)
from grag.config import ProviderType, get_config_manager
import pytest


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    input_dir = base / "input"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.entity_relation.json").write_text(content, encoding="utf-8")


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(x in url_lower for x in ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"])


def _ensure_real_llm_ready() -> None:
    settings = get_config_manager().get_settings()
    llm_cfg = settings.get_provider_config(ProviderType.LLM)
    llm_api_key = (
        __import__("os").environ.get("GRAG_LLM_API_KEY")
        or __import__("os").environ.get(getattr(llm_cfg, "api_key_env", "") or "")
    )
    if not llm_api_key and llm_cfg.base_url and not _is_local_url(llm_cfg.base_url):
        pytest.skip("LLM API key missing for non-local base_url")


@pytest.mark.integration
def test_extract_many_on_real_docs(real_doc_texts) -> None:
    _ensure_real_llm_ready()
    started_at = time.time()

    extractor = EntityRelationExtractor()
    extractor.base_sleep_seconds = 0.5
    extractor.max_retries = 2

    for p, text in real_doc_texts:
        snippet = text[:2500]
        chunks = [
            Chunk(chunk_id=f"{p.stem}_0", text=snippet[:1200]),
            Chunk(chunk_id=f"{p.stem}_1", text=snippet[1200:2400]),
        ]
        results = asyncio.run(extractor.extract_many(chunks))
        assert len(results) == 2
        assert all(isinstance(r.entity_relation_raw, str) for r in results)
        _write_outputs(
            f"{p.stem}.extract_many",
            {
                "elapsed_seconds": round(time.time() - started_at, 4),
                "doc": p.name,
                "results": [r.__dict__ for r in results],
            },
        )
