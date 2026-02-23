from __future__ import annotations

from typing import List, Optional, Sequence

from grag.data_client.milvus_client import MilvusClient

from ..types import GraphIndexRecord


class MilvusGraphIndexRepository:
    """Milvus graph_index 向量仓储。

    设计目标：
    - 单 collection 存两类向量：entity / relation，通过字段 kind 区分。
    - 支持按 group_id/doc_id 过滤（expr），避免跨组/跨文档混检。

    schema（字段）：
    - pk: VARCHAR 主键（带前缀 e:/r:，便于幂等 upsert 与批量删除）
    - kind: VARCHAR, in {"entity", "relation"}
    - group_id/doc_id: VARCHAR
    - source_id: VARCHAR（entity_id 或 relation_id）
    - name/text: VARCHAR（可读字段；text 是 embedding 的原始文本）
    - head_name/tail_name/relation_type: relation 专用（entity 留空字符串）
    - embedding: FLOAT_VECTOR

    注意：
    - 本 repository 只负责“向量与 Milvus schema/index”的事情；
      entity/relation 的文本拼接与 embedding 计算由上层（GraphBuilder）负责。
    """

    def __init__(
        self,
        client: MilvusClient,
        *,
        collection_name: str,
        upsert_strategy: str = "insert_only",
    ) -> None:
        self._client = client
        self._collection_name = str(collection_name).strip()
        self._upsert_strategy = str(upsert_strategy)

    def _ensure_pymilvus(self):
        try:
            import pymilvus

            return pymilvus
        except ImportError as e:
            raise ImportError(
                "使用 Milvus graph_index repository 需要安装 pymilvus: pip install pymilvus"
            ) from e

    def ensure_collection(self, *, dim: int) -> None:
        """确保 graph_index collection 存在。"""
        if not self._collection_name:
            raise ValueError("Milvus graph_index collection_name is required")
        if int(dim) <= 0:
            raise ValueError("Milvus graph_index dim must be > 0")

        pymilvus = self._ensure_pymilvus()
        self._client.connect()

        name = self._collection_name
        if pymilvus.utility.has_collection(name, using=self._client._alias):
            return

        fields = [
            pymilvus.FieldSchema(
                name="pk",
                dtype=pymilvus.DataType.VARCHAR,
                is_primary=True,
                auto_id=False,
                max_length=512,
            ),
            pymilvus.FieldSchema(
                name="kind",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=16,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="group_id",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=128,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="doc_id",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=128,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="source_id",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=128,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="name",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=512,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="text",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=8192,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="head_name",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=512,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="tail_name",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=512,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="relation_type",
                dtype=pymilvus.DataType.VARCHAR,
                max_length=128,
                is_primary=False,
            ),
            pymilvus.FieldSchema(
                name="embedding",
                dtype=pymilvus.DataType.FLOAT_VECTOR,
                dim=int(dim),
            ),
        ]

        schema = pymilvus.CollectionSchema(fields=fields, description="grag graph index (entity/relation embeddings)")
        col = pymilvus.Collection(name=name, schema=schema, using=self._client._alias)

        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "IP",
            "params": {"nlist": 1024},
        }
        col.create_index(field_name="embedding", index_params=index_params)
        col.load()

    def upsert_records(self, *, records: Sequence[GraphIndexRecord]) -> None:
        """写入 entity/relation 向量。"""
        if not records:
            return

        dim = len(records[0].embedding)
        for r in records:
            if len(r.embedding) != dim:
                raise ValueError("Milvus graph_index upsert requires consistent embedding dimension")

        self.ensure_collection(dim=dim)

        pymilvus = self._ensure_pymilvus()
        col = pymilvus.Collection(name=self._collection_name, using=self._client._alias)

        pks: List[str] = []
        kinds: List[str] = []
        group_ids: List[str] = []
        doc_ids: List[str] = []
        source_ids: List[str] = []
        names: List[str] = []
        texts: List[str] = []
        head_names: List[str] = []
        tail_names: List[str] = []
        relation_types: List[str] = []
        vecs: List[List[float]] = []

        for r in records:
            pks.append(r.pk)
            kinds.append(r.kind)
            group_ids.append(r.group_id)
            doc_ids.append(r.doc_id)
            source_ids.append(r.source_id)
            names.append(r.name)
            texts.append(r.text)
            head_names.append(r.head_name or "")
            tail_names.append(r.tail_name or "")
            relation_types.append(r.relation_type or "")
            vecs.append(list(r.embedding))

        if self._upsert_strategy == "delete_then_insert":
            expr = 'pk in ["' + '", "'.join(pks) + '"]'
            col.delete(expr)
        elif self._upsert_strategy != "insert_only":
            raise ValueError(
                f"Unknown Milvus graph_index upsert_strategy: {self._upsert_strategy}. Supported: insert_only, delete_then_insert"
            )

        data = [
            pks,
            kinds,
            group_ids,
            doc_ids,
            source_ids,
            names,
            texts,
            head_names,
            tail_names,
            relation_types,
            vecs,
        ]
        col.insert(data)
        col.flush()

    def search(
        self,
        *,
        group_id: str,
        kind: str,
        query_vector: Sequence[float],
        top_k: int = 10,
        doc_id: Optional[str] = None,
        output_fields: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        """在 graph_index 中做向量检索。

        返回：List[dict]，包含 output_fields + score。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if str(kind).strip().lower() not in {"entity", "relation"}:
            raise ValueError("kind must be 'entity' or 'relation'")

        qv = list(query_vector)
        if not qv:
            return []

        pymilvus = self._ensure_pymilvus()
        self._client.connect()

        if not pymilvus.utility.has_collection(self._collection_name, using=self._client._alias):
            return []

        col = pymilvus.Collection(name=self._collection_name, using=self._client._alias)

        expr_parts = [f'group_id == "{group_id}"', f'kind == "{str(kind).strip().lower()}"']
        if doc_id:
            expr_parts.append(f'doc_id == "{doc_id}"')
        expr = " and ".join(expr_parts)

        fields = (
            list(output_fields)
            if output_fields is not None
            else [
                "pk",
                "kind",
                "group_id",
                "doc_id",
                "source_id",
                "name",
                "text",
                "head_name",
                "tail_name",
                "relation_type",
            ]
        )

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
