from __future__ import annotations

from typing import List, Optional, Sequence

from grag.data_client.milvus_client import MilvusClient

from ..types import ChunkEmbeddingRecord, DocumentRecord


"""grag.storage.repositories.milvus_repository

Milvus 向量存储仓储层（Repository）。

定位：
- 本模块只负责 chunk embedding 的落库与集合（collection）初始化。
- 不负责 chunk 文本/实体元信息（Postgres）或图结构（Neo4j）。

关键约定：
- Collection schema（最小可用）：
  - pk: 主键，使用 "{group_id}:{chunk_id}"，便于跨 group 隔离且可幂等覆盖策略扩展
  - group_id/doc_id/chunk_id: 便于过滤与回溯
  - embedding: FLOAT_VECTOR，dim 由首次写入时决定

- Index：
  - 默认创建 IVF_FLAT + IP（内积）
  - 该配置主要用于最小可用；具体召回/性能参数可按业务调整

注意：
- 目前写入使用 `insert + flush`，严格意义上不是 upsert（同 pk 重复时行为取决于 Milvus 配置）。
  如果需要强幂等“覆盖写”，可在此基础上实现：delete(expr) -> insert。
"""


class MilvusVectorRepository:
    """Milvus 向量仓储。

    依赖：
    - `MilvusClient` 负责读取配置并建立连接（connect/disconnect）

    失败语义：
    - pymilvus 未安装会抛 ImportError
    - Milvus 服务不可用或建 collection/index 失败会抛 RuntimeError/Exception
    """

    def __init__(
        self,
        client: MilvusClient,
        *,
        collection_name: Optional[str] = None,
        dim: int = 0,
        upsert_strategy: str = "insert_only",
    ) -> None:
        self._client = client
        self._collection_name_override = collection_name
        self._dim = int(dim)
        self._upsert_strategy = str(upsert_strategy)

    def _ensure_pymilvus(self):
        """延迟导入 pymilvus。

        说明：
        - repository 层尽量不在 import 时强依赖第三方库，便于在未安装依赖的环境中跑纯逻辑测试。
        """
        try:
            import pymilvus
            return pymilvus
        except ImportError as e:
            raise ImportError(
                "使用 Milvus repository 需要安装 pymilvus: pip install pymilvus"
            ) from e

    def _collection_name(self) -> str:
        return self._collection_name_override or self._client.get_collection_name()

    def ensure_collection(self, *, dim: int) -> None:
        """确保 collection 存在，并为 embedding 字段创建向量索引。

        Args:
            dim:
                embedding 维度。要求 > 0。

        行为：
        - 若 collection 已存在：直接返回
        - 若不存在：创建 schema + index，并 load
        """
        pymilvus = self._ensure_pymilvus()
        self._client.connect()

        name = self._collection_name()
        if pymilvus.utility.has_collection(name, using=self._client._alias):
            return

        if dim <= 0:
            raise ValueError("Milvus collection dim must be > 0")

        fields = [
            pymilvus.FieldSchema(
                name="pk", dtype=pymilvus.DataType.VARCHAR, is_primary=True, auto_id=False, max_length=512
            ),
            pymilvus.FieldSchema(
                name="group_id", dtype=pymilvus.DataType.VARCHAR, max_length=128, is_primary=False
            ),
            pymilvus.FieldSchema(
                name="doc_id", dtype=pymilvus.DataType.VARCHAR, max_length=128, is_primary=False
            ),
            pymilvus.FieldSchema(
                name="chunk_id", dtype=pymilvus.DataType.VARCHAR, max_length=512, is_primary=False
            ),
            pymilvus.FieldSchema(
                name="embedding", dtype=pymilvus.DataType.FLOAT_VECTOR, dim=int(dim)
            ),
        ]
        schema = pymilvus.CollectionSchema(fields=fields, description="grag chunk embeddings")
        col = pymilvus.Collection(name=name, schema=schema, using=self._client._alias)

        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "IP",
            "params": {"nlist": 1024},
        }
        col.create_index(field_name="embedding", index_params=index_params)
        col.load()

    def upsert_chunk_embeddings(
        self,
        *,
        document: DocumentRecord,
        embeddings: Sequence[ChunkEmbeddingRecord],
    ) -> None:
        """写入 chunk embeddings。

        Args:
            document:
                当前文档记录（此处主要用于接口对齐与未来扩展；当前实现未直接使用）。

            embeddings:
                chunk embedding 列表。
                要求：
                - 所有向量维度一致
                - chunk_id 应与 chunk 文本落库使用的 chunk_id 一致

        失败语义：
        - dim 不一致会抛 ValueError
        - Milvus 连接/写入异常会向上抛出
        """
        pymilvus = self._ensure_pymilvus()

        if not embeddings:
            return

        dim = len(embeddings[0].vector)
        for e in embeddings:
            if len(e.vector) != dim:
                raise ValueError("Milvus upsert requires consistent embedding dimension")

        self.ensure_collection(dim=dim)

        name = self._collection_name()
        col = pymilvus.Collection(name=name, using=self._client._alias)

        pks: List[str] = []
        group_ids: List[str] = []
        doc_ids: List[str] = []
        chunk_ids: List[str] = []
        vecs: List[List[float]] = []

        for e in embeddings:
            pks.append(f"{e.group_id}:{e.chunk_id}")
            group_ids.append(e.group_id)
            doc_ids.append(e.doc_id)
            chunk_ids.append(e.chunk_id)
            vecs.append(list(e.vector))

        if self._upsert_strategy == "delete_then_insert":
            expr = 'pk in ["' + '", "'.join(pks) + '"]'
            col.delete(expr)
        elif self._upsert_strategy != "insert_only":
            raise ValueError(
                f"Unknown Milvus upsert_strategy: {self._upsert_strategy}. Supported: insert_only, delete_then_insert"
            )

        data = [pks, group_ids, doc_ids, chunk_ids, vecs]
        col.insert(data)
        col.flush()
