# GraphRAG 配置层

## 概述

配置层是GraphRAG系统的核心组件之一，负责管理所有配置相关的操作，包括配置文件的加载、验证、类型检查和运行时管理。

## 架构组件

### 1. 配置加载器 (ConfigLoader)

**文件**: `config_loader.py`

**职责**:
- 加载YAML配置文件
- 处理环境变量插值替换 (`${VAR_NAME}` 格式)
- 支持多配置文件合并
- 提供配置缓存和热重载机制

**核心特性**:
- 环境变量支持: `${ENV_VAR_NAME}` 或 `${ENV_VAR_NAME:default_value}`
- 缓存机制: 避免重复读取文件
- 文件变更检测: 自动检测配置文件的修改

### 2. 配置验证器 (ConfigValidator)

**文件**: `config_validator.py`

**职责**:
- 验证配置文件的结构和类型
- 检查必需的配置项
- 验证配置值的合理性范围
- 提供详细的验证错误信息和修复建议

**验证类型**:
- **ERROR**: 必须修复的错误，系统无法正常运行
- **WARNING**: 建议修复的警告，可能影响性能或功能
- **INFO**: 信息提示，用于优化配置

### 3. 类型化设置 (GraphRAGSettings)

**文件**: `settings.py`

**职责**:
- 提供类型安全的配置访问接口
- 使用Pydantic进行数据验证
- 定义所有配置项的数据结构

**主要配置类**:
- `LLMProviderConfig`: LLM提供商配置
- `EmbeddingProviderConfig`: 向量嵌入提供商配置
- `RerankerProviderConfig`: 重排序提供商配置
- `VectorDatabaseConfig`: 向量数据库配置
- `GraphDatabaseConfig`: 图数据库配置
- `RelationalDatabaseConfig`: 关系数据库配置
- `GraphRAGSettings`: 完整的系统配置

### 4. 配置管理器 (ConfigManager)

**文件**: `config_manager.py`

**职责**:
- 统一管理所有配置相关操作
- 提供配置的初始化和验证流程
- 管理配置的生命周期
- 提供便捷的配置访问方法

**核心功能**:
- 配置初始化和验证
- 提供商配置获取
- 配置运行时修改
- 配置导出功能

## 配置结构

### 主要配置项

```yaml
# 默认提供商选择
llm_provider: siliconflow
embedding_provider: siliconflow
reranker_provider: siliconflow  # 可选
vector_db_provider: milvus
graph_db_provider: neo4j
relational_db_provider: postgres

# 提供商具体配置
llm_providers:
  siliconflow:
    model: Qwen/Qwen3-Next-80B-A3B-Instruct
    base_url: https://api.siliconflow.cn/v1
    api_key_env: SILICONFLOW_API_KEY
    temperature: 0.1
    max_tokens: 4096

embedding_providers:
  siliconflow:
    model: BAAI/bge-m3
    dimension: 1024
    api_key_env: SILICONFLOW_API_KEY

# 数据库配置
vector_databases:
  milvus:
    host: localhost
    port: 19530
    collection_name: grag_documents

graph_databases:
  neo4j:
    uri: bolt://localhost:7687
    user: neo4j
    password_env: NEO4J_PASSWORD

relational_databases:
  postgres:
    host: localhost
    port: 5432
    database: grag
    user: postgres
    password_env: POSTGRES_PASSWORD

# 系统配置
system:
  workspace_dir: ./data
  logging:
    level: INFO
    file_path: ./logs/grag.log

# 各层配置
preprocessing:
  text_cleaning:
    remove_html: true
    normalize_whitespace: true

graph_construction:
  chunking:
    strategy: semantic
    chunk_size: 512

retrieval:
  keyword_search:
    enabled: true
    top_k: 20

monitoring:
  enabled: true
  metrics_port: 9090
```

## 使用方法

### 基本使用

```python
from grag.config import initialize_config, get_grag_settings

# 初始化配置
success = initialize_config()
if not success:
    print("配置初始化失败")
    exit(1)

# 获取设置
settings = get_grag_settings()

# 访问配置
llm_config = settings.get_provider_config(ProviderType.LLM)
embedding_config = settings.get_provider_config(ProviderType.EMBEDDING)
```

### 高级功能

```python
from grag.config import ConfigManager, validate_config

# 创建自定义配置管理器
config_manager = ConfigManager()

# 加载并验证配置
success = config_manager.initialize(validate=True)

# 获取验证结果
validation_results = config_manager.get_validation_results()

# 运行时修改配置
config_manager.set_config_value("llm_providers.siliconflow.temperature", 0.2)

# 导出配置
config_manager.export_config("exported_config.yaml")
```

### 环境变量支持

配置文件支持环境变量插值：

```yaml
llm_providers:
  siliconflow:
    api_key_env: SILICONFLOW_API_KEY  # 使用环境变量值
    base_url: ${API_BASE_URL:https://api.siliconflow.cn/v1}  # 支持默认值
```

## 环境变量

### 必需的环境变量

根据配置中的 `*_env` 字段设置相应的环境变量：

```bash
# Linux/Mac
export SILICONFLOW_API_KEY=your_api_key
export NEO4J_PASSWORD=your_password
export POSTGRES_PASSWORD=your_password

# Windows PowerShell
$env:SILICONFLOW_API_KEY="your_api_key"
$env:NEO4J_PASSWORD="your_password"
$env:POSTGRES_PASSWORD="your_password"
```

### 可选的环境变量

```bash
# 覆盖默认提供商
export GRAG_LLM_PROVIDER=openai
export GRAG_EMBEDDING_PROVIDER=openai

# 覆盖连接参数
export GRAG_NEO4J_URI=bolt://remote-host:7687
```

## 验证和调试

### 配置验证

```python
from grag.config import validate_config, print_validation_results

# 验证当前配置
results = validate_config()

# 打印验证结果
print_validation_results(results)
```

### 测试配置

运行测试脚本验证配置是否正确：

```bash
python test_config.py
```

### 常见问题

1. **配置加载失败**
   - 检查 `config/grag_config.yaml` 文件是否存在
   - 验证YAML语法是否正确

2. **环境变量未设置**
   - 检查必需的环境变量是否已设置
   - 使用 `echo $ENV_VAR_NAME` 验证变量值

3. **验证失败**
   - 查看详细的验证错误信息
   - 根据建议修复配置问题

4. **提供商配置缺失**
   - 确保 `llm_providers`、`embedding_providers` 等配置完整
   - 检查默认提供商名称是否在对应配置中定义

## 扩展配置

### 添加自定义验证器

```python
from grag.config import ConfigManager, ValidationResult, ValidationLevel

def custom_validator(config, field_path):
    """自定义验证器示例"""
    results = []

    # 检查自定义业务逻辑
    if config.get("custom_field") == "invalid_value":
        results.append(ValidationResult(
            level=ValidationLevel.ERROR,
            field_path="custom_field",
            message="自定义字段值无效",
            suggestion="请使用有效值"
        ))

    return results

# 添加自定义验证器
config_manager = ConfigManager()
config_manager.add_custom_validator("custom_section", custom_validator)
```

### 运行时配置更新

```python
from grag.config import get_config_manager

# 获取配置管理器
manager = get_config_manager()

# 更新配置值
manager.set_config_value("system.logging.level", "DEBUG")

# 重新验证配置
results = manager.validate_current_config()
```

## 依赖项

配置层需要以下Python包：

```
pydantic>=2.0.0      # 类型验证和设置管理
pyyaml>=6.0          # YAML文件解析
```

## 文件结构

```
grag/config/
├── __init__.py           # 包导出
├── config_loader.py      # 配置加载器
├── config_validator.py   # 配置验证器
├── settings.py          # 类型化设置
├── config_manager.py    # 配置管理器
└── README.md           # 本文档
```

## 设计原则

1. **类型安全**: 使用Pydantic确保配置的类型安全
2. **环境隔离**: 支持多环境配置和环境变量覆盖
3. **验证完整**: 全面验证配置的正确性和合理性
4. **易于扩展**: 支持自定义验证器和配置项
5. **运行时灵活**: 支持运行时配置更新和热重载
6. **错误友好**: 提供详细的错误信息和修复建议