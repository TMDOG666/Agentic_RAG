import sys
from pathlib import Path

from datetime import datetime, timezone

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.graph_builder import GraphBuilder
from grag.graph_construction.graph_construction_manager import GraphConstructionManager
from grag.storage import GraphStorage


class FakeStorage(GraphStorage):
    def __init__(self) -> None:
        self.called = False
        self.payload = None

    def save_document(
        self,
        *,
        document,
        chunks,
        embeddings,
        entities,
        relations,
    ) -> None:
        self.called = True
        self.payload = {
            "document": document,
            "chunks": list(chunks),
            "embeddings": list(embeddings),
            "entities": list(entities),
            "relations": list(relations),
        }


def test_graph_builder_build_and_save_with_fakes() -> None:
    # 通过 fake 函数，确保该测试不依赖真实 LLM / embedding / DB。
    def fake_coref_chat(_prompt: str) -> str:
        return "[]"

    def fake_entity_relation_chat(_prompt: str) -> str:
        return (
            "entity<|SEP|>张三<|SEP|>人物<|SEP|>文档中的人物\n"
            "entity<|SEP|>李四<|SEP|>人物<|SEP|>另一位人物\n"
            "relation<|SEP|>张三<|SEP|>李四<|SEP|>朋友关系<|SEP|>friend<|SEP|>8\n"
            "<|DONE|>\n"
        )

    def fake_fusion_chat(_prompt: str) -> str:
        return """[{\"canonical_name\":\"张三\",\"type\":\"人物\",\"aliases\":[\"张三\"],\"description\":\"人物\"}]"""

    def fake_embedding_fn(texts: list[str], _provider: str) -> list[list[float]]:
        return [[0.0, float(i)] for i in range(len(texts))]

    storage = FakeStorage()

    manager = GraphConstructionManager(
        coref_llm_chat_fn=fake_coref_chat,
        entity_relation_llm_chat_fn=fake_entity_relation_chat,
        fusion_llm_chat_fn=fake_fusion_chat,
        embedding_fn=fake_embedding_fn,
    )

    # 将 fake LLM/embedding 注入到 builder 内部的 construction manager
    builder = GraphBuilder(
        storage=storage,
        construction_manager=manager,
        embedding_fn=fake_embedding_fn,
        embedding_provider="fake",
    )

    doc_time = datetime.now(timezone.utc).isoformat()
    result = builder.build_and_save(
        text="张三和李四是朋友。",
        doc_time=doc_time,
        doc_name="unit_test_doc",
        group_id="g1",
        doc_id="d1",
    )

    assert storage.called is True
    assert storage.payload is not None

    assert result.document.group_id == "g1"
    assert result.document.doc_id == "d1"

    assert len(result.chunks) > 0
    assert len(result.embeddings) == len(result.chunks)

    # 确保 chunk_id 与 doc_id 前缀一致，方便幂等入库
    assert all(c.chunk_id.startswith("d1::chunk_") for c in result.chunks)

    # 关系与实体来自 fusion 结果
    assert len(result.entities) >= 1
