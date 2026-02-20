from __future__ import annotations

from typing import Optional, Sequence

from grag.data_client.postgres_client import PostgresClient

from ..types import ChunkRecord, DocumentRecord, GraphEntityRecord


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
                canonical_name TEXT NOT NULL,
                type TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                description TEXT NOT NULL,
                PRIMARY KEY (group_id, doc_id, canonical_name)
            );
            """,
        ]

        conn = self._client.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    for sql in ddl:
                        cur.execute(sql)
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
                        SELECT doc_id, canonical_name, type, aliases_json, description
                        FROM grag_entities
                        WHERE group_id = %s
                        ORDER BY doc_id DESC
                        LIMIT %s;
                        """,
                        (group_id, int(limit)),
                    )
                    rows = cur.fetchall()

            out: list[GraphEntityRecord] = []
            for doc_id, canonical_name, etype, aliases_json, description in rows:
                aliases: list[str] = []
                try:
                    raw = json.loads(aliases_json or "[]")
                    if isinstance(raw, list):
                        aliases = [str(x) for x in raw if str(x).strip()]
                except Exception:
                    aliases = []

                out.append(
                    GraphEntityRecord(
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
                                group_id, doc_id, canonical_name, type, aliases_json, description
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (group_id, doc_id, canonical_name)
                            DO UPDATE SET
                                type = EXCLUDED.type,
                                aliases_json = EXCLUDED.aliases_json,
                                description = EXCLUDED.description;
                            """,
                            (
                                e.group_id,
                                e.doc_id,
                                e.canonical_name,
                                e.type,
                                json.dumps(list(e.aliases), ensure_ascii=False),
                                e.description,
                            ),
                        )
        finally:
            conn.close()
