"""grag.config.settings

设置管理（Settings Management）

职责：
- 提供类型安全的配置访问接口
- 管理运行时配置修改
- 提供配置的默认值管理
- 支持配置的运行时验证

说明：
- 使用Pydantic进行类型验证
- 提供便捷的配置访问方法
- 支持配置的热更新
"""

from typing import Any, Dict, Optional, Union, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from enum import Enum
import os


class ProviderType(str, Enum):
    """提供商类型枚举"""
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    VISION = "vision"
    VECTOR_DB = "vector_db"
    GRAPH_DB = "graph_db"
    RELATIONAL_DB = "relational_db"


class LLMProviderConfig(BaseModel):
    """LLM提供商配置"""
    model: str = Field(..., description="模型名称")
    base_url: Optional[str] = Field(None, description="API基础URL")
    api_key_env: str = Field(..., description="API密钥环境变量名")
    temperature: float = Field(0.1, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(4096, gt=0, description="最大token数")
    timeout: int = Field(60, gt=0, description="请求超时时间(秒)")

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model不能为空")
        return v.strip()


class EmbeddingProviderConfig(BaseModel):
    """向量嵌入提供商配置"""
    model: str = Field(..., description="模型名称")
    base_url: Optional[str] = Field(None, description="API基础URL")
    api_key_env: Optional[str] = Field(None, description="API密钥环境变量名")
    dimension: int = Field(..., gt=0, description="向量维度")
    # 单次 embedding 请求中允许传入的最大文本条数（batch size）。
    # 不同网关/供应商限制不同（例如 64）；若超过限制常见会返回 413。
    max_batch_size: int = Field(32, gt=0, description="最大批处理大小")
    timeout: int = Field(60, gt=0, description="请求超时时间(秒)")


class RerankerProviderConfig(BaseModel):
    """重排序提供商配置"""
    model: str = Field(..., description="模型名称")
    base_url: Optional[str] = Field(None, description="API基础URL")
    api_key_env: Optional[str] = Field(None, description="API密钥环境变量名")
    top_k: int = Field(10, gt=0, description="重排序返回数量")
    timeout: int = Field(60, gt=0, description="请求超时时间(秒)")


class VectorDatabaseConfig(BaseModel):
    """向量数据库配置"""
    host: Optional[str] = Field(None, description="主机地址")
    port: Optional[int] = Field(None, gt=0, description="端口号")
    user: Optional[str] = Field(None, description="用户名")
    password: Optional[str] = Field(None, description="密码")
    password_env: Optional[str] = Field(None, description="密码环境变量")
    api_key_env: Optional[str] = Field(None, description="API密钥环境变量")
    db_name: Optional[str] = Field(None, description="数据库名")
    collection_name: str = Field(..., description="集合/索引名称")
    graph_index_collection_name: Optional[str] = Field(None, description="graph_index 集合名称")
    connection_timeout: int = Field(30, gt=0, description="连接超时时间(秒)")

    # Milvus特有
    index_type: Optional[str] = Field(None, description="索引类型")
    metric_type: Optional[str] = Field(None, description="距离度量类型")

    # Pinecone特有
    environment: Optional[str] = Field(None, description="环境")

    # Qdrant特有
    distance: Optional[str] = Field(None, description="距离度量")

    @model_validator(mode='before')
    @classmethod
    def validate_connection_params(cls, values):
        """验证连接参数"""
        if isinstance(values, dict):
            # 根据不同的数据库类型验证必需的参数
            if values.get('host') and values.get('port'):
                # 基于主机的连接
                pass
            elif values.get('api_key_env'):
                # 基于API密钥的连接
                pass
            else:
                raise ValueError("必须提供主机+端口或API密钥环境变量")
        return values


class GraphDatabaseConfig(BaseModel):
    """图数据库配置"""
    uri: Optional[str] = Field(None, description="连接URI")
    host: Optional[str] = Field(None, description="主机地址")
    port: Optional[int] = Field(None, gt=0, description="端口号")
    user: str = Field(..., description="用户名")
    password: Optional[str] = Field(None, description="密码")
    password_env: Optional[str] = Field(None, description="密码环境变量")
    database: Optional[str] = Field(None, description="数据库名")
    space: Optional[str] = Field(None, description="图空间名")
    connection_timeout: int = Field(30, gt=0, description="连接超时时间(秒)")
    max_connection_pool_size: int = Field(50, gt=0, description="最大连接池大小")


class RelationalDatabaseConfig(BaseModel):
    """关系数据库配置"""
    host: Optional[str] = Field(None, description="主机地址")
    port: Optional[int] = Field(None, gt=0, description="端口号")
    database: Optional[str] = Field(None, description="数据库名")
    database_path: Optional[str] = Field(None, description="数据库文件路径")
    user: Optional[str] = Field(None, description="用户名")
    password: Optional[str] = Field(None, description="密码")
    password_env: Optional[str] = Field(None, description="密码环境变量")
    model_config = ConfigDict(populate_by_name=True)
    db_schema: str = Field("public", alias="schema", description="数据库模式名")
    charset: str = Field("utf8mb4", description="字符集")
    connection_timeout: int = Field(30, gt=0, description="连接超时时间(秒)")
    max_connections: int = Field(20, gt=0, description="最大连接数")
    ssl_mode: str = Field("prefer", description="SSL模式")


class SystemConfig(BaseModel):
    """系统配置"""
    workspace_dir: str = Field("./data", description="工作目录")
    logging: Dict[str, Any] = Field({
        "level": "INFO",
        "file_path": "./logs/grag.log",
        "max_file_size": "100MB",
        "backup_count": 5
    }, description="日志配置")
    cache: Dict[str, Any] = Field({
        "enabled": True,
        "redis_host": "localhost",
        "redis_port": 6379,
        "redis_db": 0,
        "ttl_seconds": 3600
    }, description="缓存配置")
    monitoring: Dict[str, Any] = Field({
        "enabled": True,
        "metrics_port": 9090,
        "health_check_interval": 30
    }, description="监控配置")
    performance: Dict[str, Any] = Field({
        "max_workers": 4,
        "batch_size": 32,
        "chunk_size": 512,
        "overlap_size": 50
    }, description="性能配置")


class PreprocessingConfig(BaseModel):
    """预处理配置"""
    text_cleaning: Dict[str, Any] = Field({
        "remove_html": True,
        "remove_urls": True,
        "remove_emails": True,
        "normalize_whitespace": True,
        "remove_punctuation": False,
        "lowercase": False
    }, description="文本清洗配置")
    document_processing: Dict[str, Any] = Field({
        "supported_formats": ["pdf", "docx", "txt", "md", "html"],
        "max_file_size": "50MB",
        "encoding": "utf-8",
        "extract_metadata": True
    }, description="文档处理配置")


class GraphConstructionConfig(BaseModel):
    """图构建配置"""
    chunking: Dict[str, Any] = Field({
        "strategy": "semantic",
        "chunk_size": 512,
        "overlap": 50,
        "separator": "\n\n"
    }, description="分块配置")
    entity_resolution_knowledge_fusion: Dict[str, Any] = Field({
        "enabled": True,
        # 向量化阶段使用的 embedding provider。
        # - None: 默认取 settings.embedding_providers 的第一个 key（yaml 顺序）
        # - str : 指定 provider 名称，例如 siliconflow / openai
        "embedding_provider": None,
        # 聚类配置：默认使用 hdbscan。
        "clustering": {
            "method": "hdbscan",
            "min_cluster_size": 2,
        },
        # 融合阶段（LLM）并发数
        "fusion_bench_num": 4,
        # 可选：融合阶段使用的 LLM provider（None 表示使用 settings.llm_provider）
        "fusion_llm_provider": None,
    }, description="实体统一与知识融合（文档内部）配置")
    entity_relation_extraction: Dict[str, Any] = Field({
        "enabled": True,
        "model_provider": "siliconflow",
        "confidence_threshold": 0.7,
        "max_entities_per_chunk": 10,
        "bench_num": 4,
        "user_entity_type": [],
        "max_retries": 3,
        "base_sleep_seconds": 2.0,
    }, description="实体关系抽取配置")
    entity_extraction: Dict[str, Any] = Field({
        "enabled": True,
        "model_provider": "siliconflow",
        "confidence_threshold": 0.7,
        "max_entities_per_chunk": 10
    }, description="实体抽取配置")
    relation_extraction: Dict[str, Any] = Field({
        "enabled": True,
        "model_provider": "siliconflow",
        "confidence_threshold": 0.6,
        "max_relations_per_chunk": 15
    }, description="关系抽取配置")
    coreference_resolution: Dict[str, Any] = Field({
        "enabled": True,
        "model_provider": "siliconflow",
        "max_distance": 5,
        "bench_num": 4,
        "max_retries": 3,
        "base_sleep_seconds": 2.0,
    }, description="指代消解配置")
    graph_optimization: Dict[str, Any] = Field({
        "remove_duplicates": True,
        "merge_similar_entities": True,
        "similarity_threshold": 0.85
    }, description="图优化配置")


class RetrievalConfig(BaseModel):
    """检索配置"""
    keyword_search: Dict[str, Any] = Field({
        "enabled": True,
        "top_k": 20,
        "min_score": 0.1
    }, description="关键词检索配置")
    semantic_search: Dict[str, Any] = Field({
        "enabled": True,
        "top_k": 10,
        "similarity_threshold": 0.7,
        "rerank_enabled": True
    }, description="语义检索配置")
    graph_search: Dict[str, Any] = Field({
        "enabled": True,
        "max_depth": 3,
        "max_paths": 5,
        "relationship_weight": 0.8
    }, description="图检索配置")
    fusion_search: Dict[str, Any] = Field({
        "enabled": True,
        "weights": {
            "keyword": 0.2,
            "semantic": 0.5,
            "graph": 0.3
        },
        "top_k": 10
    }, description="融合检索配置")


class GraphRAGSettings(BaseModel):
    """GraphRAG完整配置设置"""
    # 默认提供商
    # 这些字段决定了“不显式指定 provider_name 时”系统采用哪个 provider。
    # 例如 get_provider_config(ProviderType.EMBEDDING) 会默认使用 embedding_provider。
    llm_provider: str = Field(..., description="默认LLM提供商")
    embedding_provider: str = Field(..., description="默认向量嵌入提供商")
    reranker_provider: Optional[str] = Field(None, description="默认重排序提供商")
    vision_provider: Optional[str] = Field(None, description="默认视觉模型提供商")
    vector_db_provider: str = Field(..., description="默认向量数据库")
    graph_db_provider: str = Field(..., description="默认图数据库")
    relational_db_provider: str = Field(..., description="默认关系数据库")

    # 提供商配置
    llm_providers: Dict[str, LLMProviderConfig] = Field(..., description="LLM提供商配置")
    embedding_providers: Dict[str, EmbeddingProviderConfig] = Field(..., description="向量嵌入提供商配置")
    reranker_providers: Optional[Dict[str, RerankerProviderConfig]] = Field(None, description="重排序提供商配置")
    vision_providers: Optional[Dict[str, LLMProviderConfig]] = Field(None, description="视觉模型提供商配置")

    # 数据库配置
    vector_databases: Dict[str, VectorDatabaseConfig] = Field(..., description="向量数据库配置")
    graph_databases: Dict[str, GraphDatabaseConfig] = Field(..., description="图数据库配置")
    relational_databases: Dict[str, RelationalDatabaseConfig] = Field(..., description="关系数据库配置")

    # 系统配置
    system: SystemConfig = Field(..., description="系统配置")
    preprocessing: PreprocessingConfig = Field(..., description="预处理配置")
    graph_construction: GraphConstructionConfig = Field(..., description="图构建配置")
    retrieval: RetrievalConfig = Field(..., description="检索配置")

    @model_validator(mode='before')
    @classmethod
    def validate_provider_references(cls, values):
        """验证提供商引用"""
        if isinstance(values, dict):
            llm_provider = values.get('llm_provider')
            embedding_provider = values.get('embedding_provider')
            reranker_provider = values.get('reranker_provider')
            vision_provider = values.get('vision_provider')
            vector_db_provider = values.get('vector_db_provider')
            graph_db_provider = values.get('graph_db_provider')
            relational_db_provider = values.get('relational_db_provider')

            llm_providers = values.get('llm_providers', {})
            embedding_providers = values.get('embedding_providers', {})
            reranker_providers = values.get('reranker_providers', {})
            vision_providers = values.get('vision_providers', {})
            vector_databases = values.get('vector_databases', {})
            graph_databases = values.get('graph_databases', {})
            relational_databases = values.get('relational_databases', {})

            if llm_provider and llm_provider not in llm_providers:
                raise ValueError(f"llm_provider '{llm_provider}' 不在 llm_providers 中定义")

            if embedding_provider and embedding_provider not in embedding_providers:
                raise ValueError(f"embedding_provider '{embedding_provider}' 不在 embedding_providers 中定义")

            if reranker_provider and reranker_providers and reranker_provider not in reranker_providers:
                raise ValueError(f"reranker_provider '{reranker_provider}' 不在 reranker_providers 中定义")

            if vision_provider and vision_providers and vision_provider not in vision_providers:
                raise ValueError(f"vision_provider '{vision_provider}' 不在 vision_providers 中定义")

            if vector_db_provider and vector_db_provider not in vector_databases:
                raise ValueError(f"vector_db_provider '{vector_db_provider}' 不在 vector_databases 中定义")

            if graph_db_provider and graph_db_provider not in graph_databases:
                raise ValueError(f"graph_db_provider '{graph_db_provider}' 不在 graph_databases 中定义")

            if relational_db_provider and relational_db_provider not in relational_databases:
                raise ValueError(f"relational_db_provider '{relational_db_provider}' 不在 relational_databases 中定义")

        return values

    def get_provider_config(self, provider_type: ProviderType, provider_name: Optional[str] = None) -> Any:
        """获取指定类型的提供商配置

        Args:
            provider_type: 提供商类型
            provider_name: 提供商名称，如果为None则使用默认提供商

        Returns:
            提供商配置对象
        """
        if provider_name is None:
            # 使用默认提供商
            if provider_type == ProviderType.LLM:
                provider_name = self.llm_provider
            elif provider_type == ProviderType.EMBEDDING:
                provider_name = self.embedding_provider
            elif provider_type == ProviderType.RERANKER:
                provider_name = self.reranker_provider
            elif provider_type == ProviderType.VISION:
                provider_name = self.vision_provider
            elif provider_type == ProviderType.VECTOR_DB:
                provider_name = self.vector_db_provider
            elif provider_type == ProviderType.GRAPH_DB:
                provider_name = self.graph_db_provider
            elif provider_type == ProviderType.RELATIONAL_DB:
                provider_name = self.relational_db_provider

        if provider_name is None:
            raise ValueError(f"未指定 {provider_type.value} 类型的提供商")

        # 获取对应配置
        if provider_type == ProviderType.LLM:
            return self.llm_providers[provider_name]
        elif provider_type == ProviderType.EMBEDDING:
            return self.embedding_providers[provider_name]
        elif provider_type == ProviderType.RERANKER:
            if self.reranker_providers:
                return self.reranker_providers[provider_name]
            else:
                raise ValueError("未配置重排序提供商")
        elif provider_type == ProviderType.VISION:
            if self.vision_providers:
                return self.vision_providers[provider_name]
            else:
                raise ValueError("未配置视觉模型提供商")
        elif provider_type == ProviderType.VECTOR_DB:
            return self.vector_databases[provider_name]
        elif provider_type == ProviderType.GRAPH_DB:
            return self.graph_databases[provider_name]
        elif provider_type == ProviderType.RELATIONAL_DB:
            return self.relational_databases[provider_name]
        else:
            raise ValueError(f"不支持的提供商类型: {provider_type}")

    def get_default_graph_index_collection_name(self, provider_name: Optional[str] = None) -> str:
        config = self.get_provider_config(ProviderType.VECTOR_DB, provider_name)
        value = str(getattr(config, "graph_index_collection_name", "") or "").strip()
        return value or "grag_graph_index"

    def get_env_var(self, env_var_name: str, default: Optional[str] = None) -> Optional[str]:
        """获取环境变量值

        Args:
            env_var_name: 环境变量名
            default: 默认值

        Returns:
            环境变量值
        """
        return os.environ.get(env_var_name, default)


def create_settings_from_config(config: Dict[str, Any]) -> GraphRAGSettings:
    """从配置字典创建设置对象

    Args:
        config: 配置字典

    Returns:
        GraphRAGSettings对象

    Raises:
        ValidationError: 配置验证失败
    """
    try:
        return GraphRAGSettings(**config)
    except Exception as e:
        raise ValueError(f"配置验证失败: {e}") from e
