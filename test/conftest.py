import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--pause",
        action="store",
        default="0",
        help="Pause seconds before cleanup (for manual DB inspection). Default: 0",
    )
    parser.addoption(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="Skip cleanup for integration tests (leave DB data).",
    )

    parser.addoption(
        "--group-id",
        action="store",
        default="",
    )
    parser.addoption(
        "--milvus-collection",
        action="store",
        default="",
    )
    parser.addoption(
        "--keyword-q",
        action="store",
        default="",
    )
    parser.addoption(
        "--semantic-q",
        action="store",
        default="",
    )
    parser.addoption(
        "--native-q",
        action="store",
        default="",
    )
    parser.addoption(
        "--local-q",
        action="store",
        default="",
    )
    parser.addoption(
        "--global-q",
        action="store",
        default="",
    )

    parser.addoption(
        "--print-results",
        action="store_true",
        default=False,
        help="Print full retrieval results (JSON) for integration tests. Use with -s to see output.",
    )
    parser.addoption(
        "--graph-entity",
        action="store",
        default="",
    )

    parser.addoption(
        "--pipeline-ingest",
        action="store_true",
        default=False,
        help="Run ingestion step in the full pipeline integration test (build_kg).",
    )
    parser.addoption(
        "--pipeline-cleanup",
        action="store_true",
        default=False,
        help="Force cleanup step in the full pipeline integration test (overrides --no-cleanup).",
    )
    parser.addoption(
        "--pipeline-modes",
        action="store",
        default="keyword,semantic,native,graph,local,global",
        help="Comma-separated retrieval modes to run in the full pipeline integration test.",
    )
    parser.addoption(
        "--pipeline-docs",
        action="store",
        default="2",
        help="Number of documents to ingest for the full pipeline integration test (default: 2).",
    )
    parser.addoption(
        "--pipeline-graph-index-collection",
        action="store",
        default="",
        help="Milvus graph_index collection name (default: grag_graph_index).",
    )


def get_real_docx_paths():
    from pathlib import Path

    base = Path(__file__).resolve().parent
    input_dir = base / "grag" / "test_data" / "input"
    return sorted([p for p in input_dir.iterdir() if p.is_file()])


def load_real_doc_texts(*, use_llm: bool = False):
    from grag.config import get_config_manager

    get_config_manager().initialize()

    try:
        __import__("docx")
    except ImportError as e:
        pytest.skip(f"python-docx missing: {e}")

    from grag.preprocessing.preprocessing_manager import PreprocessingManager

    processor = PreprocessingManager()
    texts = []
    for p in get_real_docx_paths():
        texts.append((p, processor.process_file(p, use_llm=use_llm)))
    return texts


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests that require real external services (LLM/embedding/DB)",
    )


@pytest.fixture(scope="session")
def real_doc_texts():
    return load_real_doc_texts(use_llm=False)
