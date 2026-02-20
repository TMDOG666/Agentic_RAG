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
    from grag.config import initialize_config, get_grag_settings

    # 初始化配置
    initialize_config()

    # 获取设置
    settings = get_grag_settings()
"""

__version__ = "0.1.0"
__author__ = "GraphRAG Team"

from .entrypoint import BuildOptions, GRAG, QueryOptions