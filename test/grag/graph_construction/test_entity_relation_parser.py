from pathlib import Path

import json

from grag.graph_construction.entity_relation_parser import parse_entity_relation_raw
from grag.graph_construction.entity_relation_extractor import Chunk, EntityRelationExtractor
from grag.config import ProviderType, get_grag_settings
import pytest
import asyncio


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.entity_relation_parsed.json").write_text(content, encoding="utf-8")


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(x in url_lower for x in ["localhost", "127.0.0.1", "0.0.0.0", "local", ".local"])


def _ensure_real_llm_ready() -> None:
    settings = get_grag_settings()
    llm_cfg = settings.get_provider_config(ProviderType.LLM)
    llm_api_key = (
        __import__("os").environ.get("GRAG_LLM_API_KEY")
        or __import__("os").environ.get(getattr(llm_cfg, "api_key_env", "") or "")
    )
    if not llm_api_key and llm_cfg.base_url and not _is_local_url(llm_cfg.base_url):
        pytest.skip("LLM API key missing for non-local base_url")


@pytest.mark.integration
def test_parse_entity_relation_raw_from_real_docs(real_doc_texts) -> None:
    _ensure_real_llm_ready()

    extractor = EntityRelationExtractor()
    extractor.base_sleep_seconds = 0.5
    extractor.max_retries = 2

    for p, text in real_doc_texts:
        snippet = text[:1800]
        chunk = Chunk(chunk_id=f"{p.stem}_0", text=snippet)
        extracted = asyncio.run(extractor.extract_many([chunk]))[0]
        parsed = parse_entity_relation_raw(extracted.entity_relation_raw)

        assert isinstance(parsed.entities, list)
        assert isinstance(parsed.relations, list)

        _write_outputs(
            f"{p.stem}.parsed",
            {
                "doc": p.name,
                "raw": extracted.entity_relation_raw,
                "entities": [e.__dict__ for e in parsed.entities],
                "relations": [r.__dict__ for r in parsed.relations],
                "errors": parsed.errors,
            },
        )
