from __future__ import annotations

from typing import Optional, Sequence

from grag.data_client.postgres_client import PostgresClient

from ..types import ChunkRecord, DocumentRecord, GraphEntityRecord, GraphRelationRecord


"""grag.storage.repositories.postgres_repository

PostgreSQL 存储仓储层（Repository）。

定位：
- 本模块只负责“关系型部分”的落库：文档元信息、chunk 文本、融合后的实体（canonical entities）。
- 不负责向量与图数据库写入（对应 Milvus / Neo4j repository）。

设计要点：
- 尽量使用幂等写入（ON CONFLICT ... DO UPDATE），便于同一 doc 重跑。
- 采用最小可用 schema：
  - grag_documents：按 (group_id, doc_id) 唯一
  - grag_chunks：按 (group_id, chunk_id) 唯一（chunk_id 内含 doc_id 前缀）
  - grag_entities：按 (group_id, doc_id, canonical_name) 唯一

说明：
- 这里的 DDL 仅用于本地/开发环境的“自举”，生产建议使用 migrations 管理。
"""


class PostgresGraphRepository:
    """PostgreSQL 图谱落库仓储。

    依赖：
    - `PostgresClient` 负责读取配置与创建连接

    注意：
    - 本类每次写入会新建连接并在 finally 关闭；连接池/长连接复用不在本模块处理。
    """

    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def ensure_schema(self) -> None:
        """确保最小表结构存在。

        副作用：
        - 执行 CREATE TABLE IF NOT EXISTS

        事务语义：
        - 使用单个事务执行全部 DDL。
        """

        ddl = [
            """
            CREATE TABLE IF NOT EXISTS grag_groups (
                group_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                group_desc TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (group_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS grag_documents (
                group_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                doc_name TEXT NOT NULL,
                doc_time TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (group_id, doc_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS grag_chunks (
                group_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (group_id, chunk_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS grag_entities (
                group_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                type TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                description TEXT NOT NULL,
                PRIMARY KEY (group_id, doc_id, canonical_name)
            );
            """,

            # 关系表：用于审计/回溯，以及为 relation_id 提供“权威来源”。
            # 说明：
            # - 当前项目的关系仍然以 Neo4j 为主用于图查询。
            # - 但为了后续 global 检索（relation embedding -> head/tail），我们也需要在关系型库保存一份。
            """
            CREATE TABLE IF NOT EXISTS grag_relations (
                group_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                relation_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                object TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                description TEXT NOT NULL,
                confidence INTEGER,
                PRIMARY KEY (group_id, relation_id)
            );
            """,
        ]

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    for sql in ddl:
                        cur.execute(sql)

                    # 兼容旧环境：历史版本可能已创建 grag_entities，但缺少 entity_id 列。
                    #
                    # 注意：
                    # - 不能依赖 "ADD COLUMN IF NOT EXISTS"（可能受 Postgres 版本/权限/语法限制）。
                    # - 因此这里先查 information_schema，缺列则执行分步迁移：
                    #   1) ADD COLUMN（先允许 NULL）
                    #   2) SET DEFAULT
                    #   3) 将历史行补齐为 ''
                    #   4) SET NOT NULL
                    cur.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'grag_entities'
                          AND column_name = 'entity_id'
                        LIMIT 1;
                        """
                    )
                    has_entity_id = cur.fetchone() is not None
                    if not has_entity_id:
                        cur.execute("ALTER TABLE grag_entities ADD COLUMN entity_id TEXT")
                        cur.execute("ALTER TABLE grag_entities ALTER COLUMN entity_id SET DEFAULT ''")
                        cur.execute("UPDATE grag_entities SET entity_id = '' WHERE entity_id IS NULL")
                        cur.execute("ALTER TABLE grag_entities ALTER COLUMN entity_id SET NOT NULL")

                    # entity_id 理论上在 (group_id, doc_id, canonical_name) 决定性生成，因此可建立唯一索引。
                    # best-effort：索引已存在时会报错，因此用 try/catch。
                    try:
                        cur.execute(
                            "CREATE UNIQUE INDEX IF NOT EXISTS grag_entities_entity_id_uq ON grag_entities (group_id, entity_id)"
                        )
                    except Exception:
                        pass
        finally:
            conn.close()


    def list_groups(self, *, limit: int = 500) -> list[str]:
        """列出当前 Postgres 中存在数据的 group_id 列表。"""
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT group_id
                        FROM (
                            SELECT DISTINCT group_id FROM grag_documents
                            UNION
                            SELECT DISTINCT group_id FROM grag_groups
                        ) g
                        ORDER BY group_id ASC
                        LIMIT %s;
                        """,
                        (int(limit),),
                    )
                    rows = cur.fetchall()
            return [str(r[0]) for r in rows if str(r[0] or "").strip()]
        finally:
            conn.close()


    def create_group(self, *, group_id: str, group_name: str = "", group_desc: str = "", created_at: str) -> None:
        """创建/更新 group 元信息。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO grag_groups (group_id, group_name, group_desc, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (group_id)
                        DO UPDATE SET
                            group_name = EXCLUDED.group_name,
                            group_desc = EXCLUDED.group_desc;
                        """,
                        (group_id, str(group_name or ""), str(group_desc or ""), str(created_at)),
                    )
        finally:
            conn.close()


    def get_document(self, *, group_id: str, doc_id: str) -> Optional[DocumentRecord]:
        """按 doc_id 读取文档元信息。"""
        import json

        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(doc_id).strip():
            return None
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT doc_id, doc_name, doc_time, metadata_json
                        FROM grag_documents
                        WHERE group_id=%s AND doc_id=%s
                        LIMIT 1;
                        """,
                        (group_id, doc_id),
                    )
                    row = cur.fetchone()
            if not row:
                return None

            doc_id_v, doc_name, doc_time, metadata_json = row
            meta = {}
            try:
                raw = json.loads(metadata_json or "{}")
                if isinstance(raw, dict):
                    meta = raw
            except Exception:
                meta = {}
            return DocumentRecord(
                group_id=str(group_id),
                doc_id=str(doc_id_v),
                doc_name=str(doc_name),
                doc_time=str(doc_time),
                metadata=meta,
            )
        finally:
            conn.close()


    def list_group_doc_ids(self, *, group_id: str, limit: int = 5000) -> list[str]:
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT doc_id
                        FROM grag_documents
                        WHERE group_id=%s
                        ORDER BY doc_time DESC, doc_id DESC
                        LIMIT %s;
                        """,
                        (group_id, int(limit)),
                    )
                    rows = cur.fetchall()
            return [str(r[0]) for r in rows if str(r[0] or "").strip()]
        finally:
            conn.close()


    def list_doc_chunk_ids(self, *, group_id: str, doc_id: str, limit: int = 200000) -> list[str]:
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(doc_id).strip():
            return []
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT chunk_id
                        FROM grag_chunks
                        WHERE group_id=%s AND doc_id=%s
                        ORDER BY chunk_index ASC
                        LIMIT %s;
                        """,
                        (group_id, doc_id, int(limit)),
                    )
                    rows = cur.fetchall()
            return [str(r[0]) for r in rows if str(r[0] or "").strip()]
        finally:
            conn.close()


    def delete_document_assets(self, *, group_id: str, doc_id: str) -> bool:
        """删除 Postgres 中该 doc 的所有资产（relations/entities/chunks/document）。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(doc_id).strip():
            return False
        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM grag_relations WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_entities WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_chunks WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    cur.execute(
                        "DELETE FROM grag_documents WHERE group_id=%s AND doc_id=%s",
                        (group_id, doc_id),
                    )
                    return bool(getattr(cur, "rowcount", 0) > 0)
        finally:
            conn.close()


    def list_group_documents(
        self,
        *,
        group_id: str,
        limit: int = 200,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> list[DocumentRecord]:
        """列出 group 下文档元信息。"""
        import json

        if not str(group_id).strip():
            raise ValueError("group_id is required")

        self.ensure_schema()

        where = ["group_id = %s"]
        params: list[object] = [group_id]
        if doc_time_start:
            where.append("doc_time >= %s")
            params.append(doc_time_start)
        if doc_time_end:
            where.append("doc_time <= %s")
            params.append(doc_time_end)

        sql = (
            "SELECT doc_id, doc_name, doc_time, metadata_json "
            "FROM grag_documents "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY doc_time DESC, doc_id DESC "
            "LIMIT %s;"
        )
        params.append(int(limit))

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()

            out: list[DocumentRecord] = []
            for doc_id, doc_name, doc_time, metadata_json in rows:
                meta = {}
                try:
                    raw = json.loads(metadata_json or "{}")
                    if isinstance(raw, dict):
                        meta = raw
                except Exception:
                    meta = {}
                out.append(
                    DocumentRecord(
                        group_id=str(group_id),
                        doc_id=str(doc_id),
                        doc_name=str(doc_name),
                        doc_time=str(doc_time),
                        metadata=meta,
                    )
                )
            return out
        finally:
            conn.close()


    def get_entity_by_id(self, *, group_id: str, entity_id: str) -> Optional[GraphEntityRecord]:
        """按 entity_id 获取实体（entity_id 在 group 内唯一）。"""
        import json

        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(entity_id or "").strip():
            return None

        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT doc_id, entity_id, canonical_name, type, aliases_json, description
                        FROM grag_entities
                        WHERE group_id = %s AND entity_id = %s
                        LIMIT 1;
                        """,
                        (group_id, entity_id),
                    )
                    row = cur.fetchone()
            if not row:
                return None

            doc_id, entity_id_v, canonical_name, etype, aliases_json, description = row
            aliases: list[str] = []
            try:
                raw = json.loads(aliases_json or "[]")
                if isinstance(raw, list):
                    aliases = [str(x) for x in raw if str(x).strip()]
            except Exception:
                aliases = []
            return GraphEntityRecord(
                entity_id=str(entity_id_v),
                group_id=str(group_id),
                doc_id=str(doc_id),
                canonical_name=str(canonical_name),
                type=str(etype),
                aliases=aliases,
                description=str(description),
            )
        finally:
            conn.close()


    def upsert_entity(self, *, entity: GraphEntityRecord) -> None:
        """插入或更新实体。"""
        import json

        if not str(entity.group_id).strip():
            raise ValueError("group_id is required")
        if not str(entity.doc_id).strip():
            raise ValueError("doc_id is required")
        if not str(entity.entity_id).strip():
            raise ValueError("entity_id is required")
        if not str(entity.canonical_name).strip():
            raise ValueError("canonical_name is required")

        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO grag_entities (
                            group_id, doc_id, entity_id, canonical_name, type, aliases_json, description
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (group_id, doc_id, canonical_name)
                        DO UPDATE SET
                            entity_id = EXCLUDED.entity_id,
                            type = EXCLUDED.type,
                            aliases_json = EXCLUDED.aliases_json,
                            description = EXCLUDED.description;
                        """,
                        (
                            entity.group_id,
                            entity.doc_id,
                            entity.entity_id,
                            entity.canonical_name,
                            entity.type,
                            json.dumps(list(entity.aliases), ensure_ascii=False),
                            entity.description,
                        ),
                    )
        finally:
            conn.close()


    def delete_entity(self, *, group_id: str, entity_id: str) -> bool:
        """按 entity_id 删除实体。"""
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(entity_id or "").strip():
            return False

        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM grag_entities
                        WHERE group_id = %s AND entity_id = %s;
                        """,
                        (group_id, entity_id),
                    )
                    return bool(getattr(cur, "rowcount", 0) > 0)
        finally:
            conn.close()


    def search_chunks_by_keyword(
        self,
        *,
        group_id: str,
        query: str,
        limit: int = 20,
        doc_id: Optional[str] = None,
        doc_time_start: Optional[str] = None,
        doc_time_end: Optional[str] = None,
    ) -> Sequence[ChunkRecord]:
        """关键词检索：在 chunk 文本中做 ILIKE 匹配。

        注意：
        - group_id 必须传入，用于避免不同组数据混淆。
        - doc_time 过滤通过 JOIN grag_documents 实现。
        - doc_time 建议使用 ISO8601（字符串比较才有意义）。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        if not str(query or "").strip():
            return []

        self.ensure_schema()

        q = f"%{query}%"
        where = ["c.group_id = %s", "c.text ILIKE %s"]
        params: list[object] = [group_id, q]

        if doc_id:
            where.append("c.doc_id = %s")
            params.append(doc_id)
        if doc_time_start:
            where.append("d.doc_time >= %s")
            params.append(doc_time_start)
        if doc_time_end:
            where.append("d.doc_time <= %s")
            params.append(doc_time_end)

        sql = (
            "SELECT c.doc_id, c.chunk_id, c.chunk_index, c.text, d.doc_time "
            "FROM grag_chunks c "
            "JOIN grag_documents d ON d.group_id = c.group_id AND d.doc_id = c.doc_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY c.doc_id DESC, c.chunk_index ASC "
            "LIMIT %s;"
        )
        params.append(int(limit))

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()

            out: list[ChunkRecord] = []
            for doc_id_v, chunk_id, idx, text, _doc_time in rows:
                out.append(
                    ChunkRecord(
                        group_id=str(group_id),
                        doc_id=str(doc_id_v),
                        chunk_id=str(chunk_id),
                        index=int(idx),
                        text=str(text),
                    )
                )
            return out
        finally:
            conn.close()


    def get_chunks_by_ids(
        self,
        *,
        group_id: str,
        chunk_ids: Sequence[str],
    ) -> Sequence[ChunkRecord]:
        """按 chunk_id 批量读取 chunk 文本。

        用途：
        - Milvus 搜到 chunk_id 后，需要回表拿 chunk 文本。
        """
        if not str(group_id).strip():
            raise ValueError("group_id is required")
        ids = [str(x) for x in chunk_ids if str(x).strip()]
        if not ids:
            return []

        self.ensure_schema()

        placeholders = ",".join(["%s"] * len(ids))
        sql = (
            "SELECT doc_id, chunk_id, chunk_index, text "
            "FROM grag_chunks "
            "WHERE group_id = %s AND chunk_id IN ("
            + placeholders
            + ")"
        )
        params: list[object] = [group_id] + ids

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()

            by_id: dict[str, ChunkRecord] = {}
            for doc_id_v, chunk_id, idx, text in rows:
                by_id[str(chunk_id)] = ChunkRecord(
                    group_id=str(group_id),
                    doc_id=str(doc_id_v),
                    chunk_id=str(chunk_id),
                    index=int(idx),
                    text=str(text),
                )

            # 保持输入顺序
            return [by_id[cid] for cid in ids if cid in by_id]
        finally:
            conn.close()

    def list_group_entities(self, *, group_id: str, limit: int = 500) -> Sequence[GraphEntityRecord]:
        """列出同一 group 下已落库的实体（用于跨文档融合候选召回）。

        数据来源：
        - grag_entities 表（doc 级实体；主键为 group_id+doc_id+canonical_name）

        返回值：
        - GraphEntityRecord 列表，其中 doc_id 为实体首次出现的 doc。
        - aliases_json 会反序列化为 aliases 列表。

        注意：
        - 这里按 doc_id DESC 简单排序，仅作为“最近写入优先”的近似策略。
        - 后续如需更强的候选召回（例如按实体频次、按时间窗口），可在 SQL 层扩展。
        """
        import json

        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT doc_id, entity_id, canonical_name, type, aliases_json, description
                        FROM grag_entities
                        WHERE group_id = %s
                        ORDER BY doc_id DESC
                        LIMIT %s;
                        """,
                        (group_id, int(limit)),
                    )
                    rows = cur.fetchall()

            out: list[GraphEntityRecord] = []
            for doc_id, entity_id, canonical_name, etype, aliases_json, description in rows:
                aliases: list[str] = []
                try:
                    raw = json.loads(aliases_json or "[]")
                    if isinstance(raw, list):
                        aliases = [str(x) for x in raw if str(x).strip()]
                except Exception:
                    aliases = []

                out.append(
                    GraphEntityRecord(
                        entity_id=str(entity_id),
                        group_id=str(group_id),
                        doc_id=str(doc_id),
                        canonical_name=str(canonical_name),
                        type=str(etype),
                        aliases=aliases,
                        description=str(description),
                    )
                )
            return out
        finally:
            conn.close()

    def upsert_document_and_chunks(
        self,
        *,
        document: DocumentRecord,
        chunks: Sequence[ChunkRecord],
        entities: Sequence[GraphEntityRecord],
        relations: Sequence[GraphRelationRecord],
    ) -> None:
        """将文档、chunk、实体落入 PostgreSQL。

        Args:
            document:
                文档级元信息。按 (group_id, doc_id) 幂等 upsert。

            chunks:
                chunk 文本列表。按 (group_id, chunk_id) 幂等 upsert。
                约定：chunk_id 推荐使用 "{doc_id}::chunk_{i}" 的稳定格式。

            entities:
                融合后的 canonical entities。按 (group_id, doc_id, canonical_name) 幂等 upsert。

        副作用：
        - 创建 schema（best-effort）
        - 写入/更新三张表

        失败语义：
        - 任何 SQL 异常将导致事务回滚并向上抛出。
        """
        import json

        self.ensure_schema()

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO grag_documents (group_id, doc_id, doc_name, doc_time, metadata_json)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (group_id, doc_id)
                        DO UPDATE SET
                            doc_name = EXCLUDED.doc_name,
                            doc_time = EXCLUDED.doc_time,
                            metadata_json = EXCLUDED.metadata_json;
                        """,
                        (
                            document.group_id,
                            document.doc_id,
                            document.doc_name,
                            document.doc_time,
                            json.dumps(document.metadata, ensure_ascii=False),
                        ),
                    )

                    for c in chunks:
                        cur.execute(
                            """
                            INSERT INTO grag_chunks (group_id, doc_id, chunk_id, chunk_index, text)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (group_id, chunk_id)
                            DO UPDATE SET
                                doc_id = EXCLUDED.doc_id,
                                chunk_index = EXCLUDED.chunk_index,
                                text = EXCLUDED.text;
                            """,
                            (c.group_id, c.doc_id, c.chunk_id, int(c.index), c.text),
                        )

                    for e in entities:
                        cur.execute(
                            """
                            INSERT INTO grag_entities (
                                group_id, doc_id, entity_id, canonical_name, type, aliases_json, description
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (group_id, doc_id, canonical_name)
                            DO UPDATE SET
                                entity_id = EXCLUDED.entity_id,
                                type = EXCLUDED.type,
                                aliases_json = EXCLUDED.aliases_json,
                                description = EXCLUDED.description;
                            """,
                            (
                                e.group_id,
                                e.doc_id,
                                e.entity_id,
                                e.canonical_name,
                                e.type,
                                json.dumps(list(e.aliases), ensure_ascii=False),
                                e.description,
                            ),
                        )

                    for r in relations:
                        cur.execute(
                            """
                            INSERT INTO grag_relations (
                                group_id, doc_id, relation_id, subject, object, relation_type, description, confidence
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (group_id, relation_id)
                            DO UPDATE SET
                                doc_id = EXCLUDED.doc_id,
                                subject = EXCLUDED.subject,
                                object = EXCLUDED.object,
                                relation_type = EXCLUDED.relation_type,
                                description = EXCLUDED.description,
                                confidence = EXCLUDED.confidence;
                            """,
                            (
                                r.group_id,
                                r.doc_id,
                                r.relation_id,
                                r.subject,
                                r.object,
                                r.relation_type,
                                r.description,
                                r.confidence,
                            ),
                        )
        finally:
            conn.close()
