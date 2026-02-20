"""测试设置管理 (Settings)"""

import os

from grag.config.settings import (
    GraphRAGSettings,
    ProviderType,
    create_settings_from_config,
    get_settings
)
from grag.config.config_loader import load_grag_config


class TestSettings:
    """测试 Settings 模块"""

    def test_create_settings_from_config(self):
        """测试从配置创建设置对象"""
        print("\n=== 测试从配置创建设置对象 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        assert settings is not None, "设置对象不应为空"
        assert isinstance(settings, GraphRAGSettings), "应该是 GraphRAGSettings 类型"
        
        print(f"✅ 设置对象创建成功")
        print(f"   类型: {type(settings).__name__}")

    def test_settings_attributes(self):
        """测试设置对象属性"""
        print("\n=== 测试设置对象属性 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 验证默认提供商
        assert hasattr(settings, 'llm_provider'), "应有 llm_provider 属性"
        assert hasattr(settings, 'embedding_provider'), "应有 embedding_provider 属性"
        assert hasattr(settings, 'vector_db_provider'), "应有 vector_db_provider 属性"
        assert hasattr(settings, 'graph_db_provider'), "应有 graph_db_provider 属性"
        assert hasattr(settings, 'relational_db_provider'), "应有 relational_db_provider 属性"
        
        print(f"✅ 默认提供商:")
        print(f"   LLM: {settings.llm_provider}")
        print(f"   Embedding: {settings.embedding_provider}")
        print(f"   Vector DB: {settings.vector_db_provider}")
        print(f"   Graph DB: {settings.graph_db_provider}")
        print(f"   Relational DB: {settings.relational_db_provider}")

    def test_llm_provider_config(self):
        """测试 LLM 提供商配置"""
        print("\n=== 测试 LLM 提供商配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 获取默认 LLM 配置
        llm_config = settings.get_provider_config(ProviderType.LLM)
        
        assert llm_config is not None, "LLM 配置不应为空"
        assert hasattr(llm_config, 'model'), "应有 model 属性"
        assert hasattr(llm_config, 'temperature'), "应有 temperature 属性"
        assert hasattr(llm_config, 'max_tokens'), "应有 max_tokens 属性"
        
        print(f"✅ LLM 配置:")
        print(f"   模型: {llm_config.model}")
        print(f"   温度: {llm_config.temperature}")
        print(f"   最大 tokens: {llm_config.max_tokens}")
        print(f"   超时: {llm_config.timeout}s")

    def test_embedding_provider_config(self):
        """测试 Embedding 提供商配置"""
        print("\n=== 测试 Embedding 提供商配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 获取默认 Embedding 配置
        embedding_config = settings.get_provider_config(ProviderType.EMBEDDING)
        
        assert embedding_config is not None, "Embedding 配置不应为空"
        assert hasattr(embedding_config, 'model'), "应有 model 属性"
        assert hasattr(embedding_config, 'dimension'), "应有 dimension 属性"
        
        print(f"✅ Embedding 配置:")
        print(f"   模型: {embedding_config.model}")
        print(f"   维度: {embedding_config.dimension}")
        print(f"   批处理大小: {embedding_config.max_batch_size}")

    def test_vector_db_config(self):
        """测试向量数据库配置"""
        print("\n=== 测试向量数据库配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 获取 Milvus 配置
        milvus_config = settings.get_provider_config(
            ProviderType.VECTOR_DB,
            "milvus"
        )
        
        assert milvus_config is not None, "Milvus 配置不应为空"
        assert milvus_config.host == "localhost", "主机应为 localhost"
        assert milvus_config.port == 19530, "端口应为 19530"
        
        print(f"✅ Milvus 配置:")
        print(f"   主机: {milvus_config.host}")
        print(f"   端口: {milvus_config.port}")
        print(f"   数据库: {milvus_config.db_name}")
        print(f"   集合: {milvus_config.collection_name}")

    def test_graph_db_config(self):
        """测试图数据库配置"""
        print("\n=== 测试图数据库配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 获取 Neo4j 配置
        neo4j_config = settings.get_provider_config(
            ProviderType.GRAPH_DB,
            "neo4j"
        )
        
        assert neo4j_config is not None, "Neo4j 配置不应为空"
        assert neo4j_config.uri is not None, "URI 不应为空"
        assert neo4j_config.user == "neo4j", "用户应为 neo4j"
        
        print(f"✅ Neo4j 配置:")
        print(f"   URI: {neo4j_config.uri}")
        print(f"   用户: {neo4j_config.user}")
        print(f"   数据库: {neo4j_config.database}")
        print(f"   连接池大小: {neo4j_config.max_connection_pool_size}")

    def test_relational_db_config(self):
        """测试关系数据库配置"""
        print("\n=== 测试关系数据库配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        # 获取 PostgreSQL 配置
        postgres_config = settings.get_provider_config(
            ProviderType.RELATIONAL_DB,
            "postgres"
        )
        
        assert postgres_config is not None, "PostgreSQL 配置不应为空"
        assert postgres_config.host == "localhost", "主机应为 localhost"
        assert postgres_config.port == 5430, "端口应为 5430"
        assert postgres_config.database == "grag", "数据库应为 grag"
        
        print(f"✅ PostgreSQL 配置:")
        print(f"   主机: {postgres_config.host}")
        print(f"   端口: {postgres_config.port}")
        print(f"   数据库: {postgres_config.database}")
        print(f"   用户: {postgres_config.user}")
        print(f"   Schema: {postgres_config.db_schema}")

    def test_system_config(self):
        """测试系统配置"""
        print("\n=== 测试系统配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        assert hasattr(settings, 'system'), "应有 system 属性"
        system = settings.system
        
        assert hasattr(system, 'workspace_dir'), "应有 workspace_dir"
        assert hasattr(system, 'logging'), "应有 logging 配置"
        assert hasattr(system, 'cache'), "应有 cache 配置"
        
        print(f"✅ 系统配置:")
        print(f"   工作目录: {system.workspace_dir}")
        print(f"   日志级别: {system.logging.get('level')}")
        print(f"   缓存启用: {system.cache.get('enabled')}")

    def test_preprocessing_config(self):
        """测试预处理配置"""
        print("\n=== 测试预处理配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        assert hasattr(settings, 'preprocessing'), "应有 preprocessing 属性"
        preprocessing = settings.preprocessing
        
        assert hasattr(preprocessing, 'text_cleaning'), "应有 text_cleaning"
        assert hasattr(preprocessing, 'document_processing'), "应有 document_processing"
        
        print(f"✅ 预处理配置:")
        print(f"   文本清洗: {preprocessing.text_cleaning}")
        print(f"   文档处理: {preprocessing.document_processing}")

    def test_graph_construction_config(self):
        """测试图构建配置"""
        print("\n=== 测试图构建配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        assert hasattr(settings, 'graph_construction'), "应有 graph_construction 属性"
        graph_construction = settings.graph_construction
        
        assert hasattr(graph_construction, 'chunking'), "应有 chunking"
        assert hasattr(graph_construction, 'entity_extraction'), "应有 entity_extraction"
        assert hasattr(graph_construction, 'relation_extraction'), "应有 relation_extraction"
        
        print(f"✅ 图构建配置:")
        print(f"   分块策略: {graph_construction.chunking.get('strategy')}")
        print(f"   实体抽取: {graph_construction.entity_extraction.get('enabled')}")
        print(f"   关系抽取: {graph_construction.relation_extraction.get('enabled')}")

    def test_retrieval_config(self):
        """测试检索配置"""
        print("\n=== 测试检索配置 ===")
        
        config = load_grag_config()
        settings = create_settings_from_config(config)
        
        assert hasattr(settings, 'retrieval'), "应有 retrieval 属性"
        retrieval = settings.retrieval
        
        assert hasattr(retrieval, 'keyword_search'), "应有 keyword_search"
        assert hasattr(retrieval, 'semantic_search'), "应有 semantic_search"
        assert hasattr(retrieval, 'graph_search'), "应有 graph_search"
        assert hasattr(retrieval, 'fusion_search'), "应有 fusion_search"
        
        print(f"✅ 检索配置:")
        print(f"   关键词检索: {retrieval.keyword_search.get('enabled')}")
        print(f"   语义检索: {retrieval.semantic_search.get('enabled')}")
        print(f"   图检索: {retrieval.graph_search.get('enabled')}")
        print(f"   融合检索: {retrieval.fusion_search.get('enabled')}")

    def test_get_settings_function(self):
        """测试全局 get_settings 函数"""
        print("\n=== 测试全局 get_settings 函数 ===")
        
        settings = get_settings()
        
        assert settings is not None, "设置不应为空"
        assert isinstance(settings, GraphRAGSettings), "应该是 GraphRAGSettings 类型"
        
        print(f"✅ 全局设置获取成功")
        print(f"   LLM 提供商: {settings.llm_provider}")
