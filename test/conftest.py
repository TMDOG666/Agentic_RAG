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


def get_real_docx_paths():
    from pathlib import Path

    base = Path(__file__).resolve().parent
    input_dir = base / "grag" / "test_data" / "input"
    return sorted([p for p in input_dir.iterdir() if p.is_file()])


def load_real_doc_texts(*, use_llm: bool = False):
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
