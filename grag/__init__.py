"""grag

GraphRAG模块

GraphRAG（Graph Retrieval-Augmented Generation）是一个基于知识图谱的检索增强生成系统。

主要层次：
- model: 模型层 - LLM和向量嵌入模型集成
- data: 数据层 - 数据库集成（Neo4j、Milvus、PostgreSQL）
- preprocessing: 预处理层 - 文本清洗和文档处理
- graph_construction: 图构建层 - 知识图谱构建
- retrieval: 检索层 - 多模态检索策略
- monitoring: 监控层 - 系统监控和日志
- config: 配置层 - 系统配置管理

使用示例：
    from grag.config import get_config_manager

    cm = get_config_manager()
    cm.initialize()
    settings = cm.get_settings()
"""

__version__ = "0.1.0"
__author__ = "GraphRAG Team"


def __getattr__(name: str):
    if name in {"GRAG", "BuildOptions", "QueryOptions"}:
        from .entrypoint import BuildOptions, GRAG, QueryOptions

        return {"GRAG": GRAG, "BuildOptions": BuildOptions, "QueryOptions": QueryOptions}[name]
    raise AttributeError(name)


__all__ = [
    "GRAG",
    "BuildOptions",
    "QueryOptions",
]