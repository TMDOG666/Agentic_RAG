# GraphRAG 配置模块（`grag.config`）

本 README 描述 `grag/config` 子模块的结构、对外接口和推荐调用方式。

从本次整理开始，配置层遵循 **单入口、单缓存** 原则：

- 只允许通过 `get_config_manager()` 获取全局 `ConfigManager` singleton，并通过它访问配置。

- 不再提供“隐式加载配置文件”的旧 helper（例如 loader/settings 层的全局函数）。

这能避免：

- 两套 singleton 导致配置来源不一致
- 测试时缓存污染、初始化顺序不确定

## 快速开始

```python
from grag.config import get_config_manager, ProviderType

cm = get_config_manager()
assert cm.initialize() is True
settings = cm.get_settings()

llm_cfg = settings.get_provider_config(ProviderType.LLM)
emb_cfg = settings.get_provider_config(ProviderType.EMBEDDING)
```

说明：

- `ConfigManager.get_settings()` / `get_config()` / `get_provider_config()` 等方法会在首次使用时自动 `initialize()`。
  但在应用入口显式 `cm.initialize()` 仍然推荐（失败能更早暴露）。

## 目录结构与职责

```
grag/config/
├── __init__.py
├── config_loader.py
├── config_validator.py
├── settings.py
├── config_manager.py
└── README.md
```

- **config_loader.py / ConfigLoader**
  - 读取 YAML（默认 `config/grag_config.yaml`）
  - 处理 `${ENV}` / `${ENV:default}` 字符串插值
  - 提供缓存与热重载（基于 checksum）

- **config_validator.py / ConfigValidator**
  - 结构/合理性验证（必填字段、provider 引用是否存在、数值范围等）
  - 产出 `ValidationResult` 列表（ERROR/WARNING/INFO）

- **settings.py / GraphRAGSettings（Pydantic）**
  - 将 raw dict 配置转为强类型对象
  - 统一默认值、字段类型校验
  - 对外提供 `GraphRAGSettings.get_provider_config()`

- **config_manager.py / ConfigManager（权威入口）**
  - 串联 `ConfigLoader -> ConfigValidator -> GraphRAGSettings`
  - 保存 config/settings/validation_results 的生命周期状态
  - 作为唯一对外入口（通过 `get_config_manager()` 获取 singleton）

## 对外接口（Public API）

推荐仅从 `grag.config` 导入以下接口（`grag/config/__init__.py` 已 re-export）：

- **get_config_manager() -> ConfigManager**
  - 获取全局配置管理器 singleton（唯一入口）
  - 方法：
    - `initialize(config_name="grag_config.yaml", validate=True) -> bool`
    - `get_settings() -> GraphRAGSettings`
    - `get_config() -> dict`
    - `get_provider_config(provider_type, provider_name=None)`
    - `validate_current_config() -> list[ValidationResult]`
    - `reload_config()` / `set_config_value()` 等

## 推荐调用流程（初始化与读取）

应用入口：

1. `cm = get_config_manager()`
2. `cm.initialize()`
3. `settings = cm.get_settings()`
3. 各模块从 settings 读取配置

模块内部（非入口处）：

- 只调用 `get_config_manager().get_settings()`（或直接复用已注入的 settings），不要自行读取 YAML。

## 配置文件概览（schema 方向）

默认配置文件路径：

- `config/grag_config.yaml`

顶级字段示例（只展示骨架，具体字段见项目的 `config/grag_config.yaml`）：

```yaml
llm_provider: siliconflow
embedding_provider: siliconflow
vector_db_provider: milvus
graph_db_provider: neo4j
relational_db_provider: postgres

llm_providers:
  siliconflow:
    model: ...
    base_url: ...
    api_key_env: ...

embedding_providers:
  siliconflow:
    model: ...
    dimension: 1024
    max_batch_size: 64

vector_databases:
  milvus:
    host: ...
    port: 19530
    collection_name: ...

graph_databases:
  neo4j:
    uri: ...
    user: ...
    password_env: ...

relational_databases:
  postgres:
    host: ...
    port: ...
    database: ...
    user: ...
    password_env: ...

system:
  workspace_dir: ./data
  logging: {...}
  monitoring: {...}

graph_construction: {...}
retrieval: {...}
```

## 环境变量插值（`${ENV}`）

`ConfigLoader` 支持在 YAML 值中写：

- `${ENV_VAR_NAME}`
- `${ENV_VAR_NAME:default_value}`

示例：

```yaml
llm_providers:
  siliconflow:
    base_url: ${API_BASE_URL:https://api.siliconflow.cn/v1}
```

## 常见问题（Troubleshooting）

- **Q: 为什么我没调用 initialize 也能跑？**
  - A: `ConfigManager` 的读取方法会在首次使用时尝试自动 `initialize()`；但入口处显式初始化更可控。

- **Q: 修改了 YAML 为什么不生效？**
  - A: `ConfigLoader` 有缓存（checksum）。你可以：
    - 调 `ConfigManager.reload_config()`
    - 或重启进程

- **Q: embeddings 报 413 / batch size exceeded？**
  - A: provider 的 batch size 需要在 `embedding_providers.<name>.max_batch_size` 中正确设置；客户端侧会按该值分批。

- **Q: pytest 收集阶段报缺包（例如 langchain_openai）？**
  - A: 确保 pytest 运行在正确的虚拟环境/conda env 中（你的依赖必须安装在同一个 python 里）。