from pathlib import Path

import asyncio
import json

from grag.graph_construction.coreference_resolver import CoreferenceResolver
from grag.config import ProviderType, get_grag_settings
import pytest


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.coreference.json").write_text(content, encoding="utf-8")


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
def test_coreference_on_real_docs(real_doc_texts) -> None:
    _ensure_real_llm_ready()

    resolver = CoreferenceResolver()
    resolver.base_sleep_seconds = 0.5
    resolver.max_retries = 2

    for p, text in real_doc_texts:
        assert isinstance(text, str) and text.strip()
        snippet = text[:1500]
        result = asyncio.run(resolver.resolve_text(snippet))
        assert result.text == snippet
        assert isinstance(result.coreference_raw, str)
        assert isinstance(result.resolved_text, str)
        # 允许 LLM 返回空列表；但无论成功/失败，resolved_text 都必须是字符串。
        _write_outputs(
            f"{p.stem}.coreference",
            {
                "doc": p.name,
                "text": result.text,
                "coreference_raw": result.coreference_raw,
                "resolved_text": result.resolved_text,
                "error": result.error,
            },
        )
