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
  - doc_time: 文档时间（字符串），用于向量检索时做时间过滤（例如只搜最近一周）
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
            # 兼容性说明：
            # - 旧版本 collection 可能没有 doc_time 字段。
            # - Milvus 不支持在不重建 collection 的情况下“在线新增字段”。
            # - 为了保证按时间过滤的功能可用，这里检测到缺字段时直接报错，提示用户 drop/recreate。
            col = pymilvus.Collection(name=name, using=self._client._alias)
            try:
                fields = [f.name for f in getattr(col.schema, "fields", [])]
            except Exception:
                fields = []

            if "doc_time" not in set(fields):
                raise RuntimeError(
                    "Milvus collection schema is missing required field 'doc_time'. "
                    "Please drop and recreate the collection to enable time filtering. "
                    f"collection={name}"
                )
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
                name="doc_time", dtype=pymilvus.DataType.VARCHAR, max_length=128, is_primary=False
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
        doc_times: List[str] = []
        chunk_ids: List[str] = []
        vecs: List[List[float]] = []

        # 写入说明：
        # - doc_time 使用 document.doc_time（同一文档的所有 chunk 相同），便于 Milvus 做 expr 过滤。
        # - 建议 doc_time 使用 ISO8601（如 2026-02-17T08:30:54Z），这样字符串比较也具有一定可用性。
        #   如果需要严格时间范围过滤，建议统一用 epoch 秒/毫秒字符串存储。
        for e in embeddings:
            pks.append(f"{e.group_id}:{e.chunk_id}")
            group_ids.append(e.group_id)
            doc_ids.append(e.doc_id)
            doc_times.append(str(document.doc_time))
            chunk_ids.append(e.chunk_id)
            vecs.append(list(e.vector))

        if self._upsert_strategy == "delete_then_insert":
            expr = 'pk in ["' + '", "'.join(pks) + '"]'
            col.delete(expr)
        elif self._upsert_strategy != "insert_only":
            raise ValueError(
                f"Unknown Milvus upsert_strategy: {self._upsert_strategy}. Supported: insert_only, delete_then_insert"
            )

        data = [pks, group_ids, doc_ids, doc_times, chunk_ids, vecs]
        col.insert(data)
        col.flush()


    def search_chunk_embeddings(
        self,
        *,
        group_id: str,
        query_vector: Sequence[float],
        top_k: int = 10,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        """向量检索（chunk 级）。

        约束：
        - group_id 必填，避免不同组混检。
        - doc_time 过滤使用字符串比较表达式，因此 doc_time 建议使用 ISO8601。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        qv = list(query_vector)
        if not qv:
            return []

        pymilvus = self._ensure_pymilvus()
        self._client.connect()

        name = self._collection_name()
        if not pymilvus.utility.has_collection(name, using=self._client._alias):
            return []

        col = pymilvus.Collection(name=name, using=self._client._alias)

        expr_parts = [f'group_id == "{group_id}"']
        if doc_id:
            expr_parts.append(f'doc_id == "{doc_id}"')
        if doc_time_start:
            expr_parts.append(f'doc_time >= "{doc_time_start}"')
        if doc_time_end:
            expr_parts.append(f'doc_time <= "{doc_time_end}"')
        expr = " and ".join(expr_parts)

        fields = list(output_fields) if output_fields is not None else ["pk", "group_id", "doc_id", "doc_time", "chunk_id"]

        # metric_type 以 collection index 的配置为准；这里不强制覆写。
        res = col.search(
            data=[qv],
            anns_field="embedding",
            param={"nprobe": 16},
            limit=int(top_k),
            expr=expr,
            output_fields=fields,
            consistency_level="Strong",
        )

        out: List[dict] = []
        for hits in res:
            for h in hits:
                entity = getattr(h, "entity", None)
                row = {}
                if entity is not None:
                    for f in fields:
                        try:
                            row[f] = entity.get(f)
                        except Exception:
                            pass
                row["score"] = float(getattr(h, "score", 0.0))
                out.append(row)
        return out
