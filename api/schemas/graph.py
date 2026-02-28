from __future__ import annotations

"""api.schemas.graph

图谱输出 schema。

说明：
- 当前图谱数据来自 Neo4j 的查询结果，按 nodes/edges 两个 list 返回。
- nodes/edges 的内部字段保持为 dict（不在 API 层强约束），便于快速迭代。
"""

from pydantic import BaseModel


class GraphOut(BaseModel):
    """图谱输出结构。"""

    nodes: list[dict]
    edges: list[dict]
