# GraphRAG Model层

## 概述

Model层是GraphRAG系统的AI模型集成层，负责管理所有AI模型的生命周期，包括：

- **LLM (Large Language Models)**: 文本生成和推理
- **Embedding Models**: 文本向量化
- **Reranker Models**: 检索结果重排序（可选）
- **Vision Models**: OCR/图像理解（可选）

## 架构组件

### 1. LLM客户端 (llm_client.py)

**核心功能**:
- 支持多种LLM提供商（OpenAI、硅基流动、vLLM、Ollama等）
- 统一的ChatOpenAI接口
- 环境变量覆盖配置
- 连接测试和错误处理

**支持的提供商**:
- siliconflow: 硅基流动
- openai: OpenAI官方
- openai_compatible: OpenAI兼容接口
- vllm: 本地vLLM服务
- ollama: Ollama本地模型

### 2. 嵌入客户端 (embedding_client.py)

**核心功能**:
- 文本向量化处理
- 支持批量嵌入
- 维度验证和自动检测
- 多提供商支持

**支持的提供商**:
- siliconflow: 硅基流动嵌入服务
- openai: OpenAI嵌入模型
- openai_compatible: 兼容的嵌入服务
- huggingface: 本地HuggingFace模型

### 3. 重排序客户端 (reranker_client.py)

**核心功能**:
- 检索结果相关性重排序
- 基于交叉编码器的重排序
- 可选功能，支持降级到无重排序
- 批处理重排序

**支持的提供商**:
- siliconflow: 硅基流动重排序服务
- openai: OpenAI重排序模型

### 4. 模型管理器 (model_manager.py)

**核心功能**:
- 统一管理所有模型实例
- 模型缓存和懒加载
- 模型状态监控
- 批量操作和测试

**管理功能**:
- 模型初始化和缓存
- 连接测试和健康检查
- 配置更新和刷新
- 资源清理

## 使用方法

### 基本使用

```python
from grag.model.llm_client import get_llm_client
from grag.model.embedding_client import get_embedding_client
from grag.model.reranker_client import get_reranker_client

# 使用 LLM
llm = get_llm_client()
model = llm.get_model()
response = model.invoke([{"role": "user", "content": "Hello"}])

# 使用 Embedding
emb = get_embedding_client()
embeddings = emb.embed_texts(["text1", "text2"])
query_embedding = emb.embed_query("query text")

# 使用 Reranker（可选）
reranker = get_reranker_client()
if reranker is not None and reranker.is_available():
    reranked_docs = reranker.rerank("query", ["doc1", "doc2", "doc3"], top_k=3)

# 使用视觉（如果需要）
# from grag.model.vision_client import VisionClient
# vision = VisionClient()
# text = vision.ocr_image("a.png")
```

### 高级功能

```python
from grag.model.llm_client import get_llm_client
from grag.model.embedding_client import get_embedding_client

# 指定提供商
llm_client = get_llm_client("openai")
embedding_client = get_embedding_client("huggingface")

# 测试连接
llm_ok = llm_client.test_connection()
embedding_ok = embedding_client.test_connection()

# 更多示例请参考各 client 的模块文档与测试用例。
```

## 推荐调用入口（重要）

本目录目前存在多套“可用入口”，建议按场景统一：

当前仓库已移除 `ModelManager`（方案 A）。建议统一使用各 client 的入口：

- `grag.model.llm_client.LLMClient` / `get_llm_client`
- `grag.model.embedding_client.EmbeddingClient` / `get_embedding_client`
- `grag.model.reranker_client.RerankerClient` / `get_reranker_client`
- `grag.model.vision_client.VisionClient` / `get_vision_client`

## 是否存在冗余？（当前实现的主要重叠点）

### 1) 模块级全局单例并存

每个 client 文件提供了自己的模块级全局单例：
  - `llm_client.get_llm_client()` / `_default_llm_client`
  - `embedding_client.get_embedding_client()` / `_default_embedding_client`
  - `reranker_client.get_reranker_client()` / `_default_reranker_client`
  - `vision_client.get_vision_client()` / `_default_vision_client`

这会导致：

- 如果代码里混用 `get_model_manager().get_llm_client()` 和 `get_llm_client()`，
  可能拿到两套不同实例（不同缓存层），出现“状态不一致/重复初始化”的困扰。

**建议**：在业务代码里统一选一种获取方式（例如始终用各模块 `get_*_client()`），避免自己再造新的缓存层。

## 文件结构

### 环境变量配置

```bash
# LLM配置
export GRAG_LLM_PROVIDER=siliconflow
export GRAG_LLM_MODEL=Qwen/Qwen3-Next-80B-A3B-Instruct
export GRAG_LLM_BASE_URL=https://api.siliconflow.cn/v1
export GRAG_LLM_API_KEY=your_api_key
export GRAG_LLM_TEMPERATURE=0.1

# 嵌入配置
export GRAG_EMBEDDING_PROVIDER=siliconflow
export GRAG_EMBEDDING_MODEL=BAAI/bge-m3

# 重排序配置
export GRAG_RERANKER_PROVIDER=siliconflow
export GRAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

## 配置结构

### grag_config.yaml 中的模型配置

```yaml
# 默认提供商
llm_provider: siliconflow
embedding_provider: siliconflow
reranker_provider: siliconflow  # 可选

# LLM提供商配置
llm_providers:
  siliconflow:
    model: Qwen/Qwen3-Next-80B-A3B-Instruct
    base_url: https://api.siliconflow.cn/v1
    api_key_env: SILICONFLOW_API_KEY
    temperature: 0.1
    max_tokens: 4096
    timeout: 60

# 嵌入提供商配置
embedding_providers:
  siliconflow:
    model: BAAI/bge-m3
    dimension: 1024
    max_batch_size: 32
    api_key_env: SILICONFLOW_API_KEY

# 重排序提供商配置（可选）
reranker_providers:
  siliconflow:
    model: BAAI/bge-reranker-v2-m3
    top_k: 10
    api_key_env: SILICONFLOW_API_KEY
```

## 模型切换

### 运行时切换提供商

```python
# 切换LLM提供商
llm_client_vllm = get_llm_client("vllm")
llm_client_openai = get_llm_client("openai")

# 切换嵌入提供商
embedding_client_local = get_embedding_client("huggingface")
embedding_client_cloud = get_embedding_client("siliconflow")
```

### 配置更新后刷新

```python
# 配置变更后刷新模型
manager.refresh_all_models()
# 或刷新特定模型
manager.refresh_model("llm", "siliconflow")
```

## 性能优化

### 模型缓存

- **懒加载**: 模型在首次使用时才初始化
- **实例缓存**: 相同配置的模型实例会被缓存复用
- **连接池**: 支持连接池管理减少初始化开销

### 批处理优化

```python
# 批量嵌入处理
texts = ["text1", "text2", "text3", "text4", "text5"]
embeddings = manager.embed_texts(texts)  # 自动批处理

# 批处理重排序
documents = ["doc1", "doc2", "doc3", "doc4", "doc5"]
reranked = manager.rerank_documents("query", documents, top_k=3)
```

## 监控和调试

### 连接测试

```python
from grag.model import test_model_connections

# 测试所有模型连接
results = test_model_connections()
print("连接状态:", results)
```

### 模型状态监控

```python
# 获取模型状态
status = manager.get_model_status()
for model_name, model_status in status.items():
    print(f"{model_name}: {model_status}")

# 获取模型信息
info = manager.get_model_info()
print("模型配置:", info)
```

### 调试模式

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 启用详细日志
# 模型操作会输出详细的调试信息
```

## 错误处理

### 常见错误及解决方案

1. **API Key错误**
   ```
   错误: API Key 不能为空
   解决: 检查环境变量设置，如 SILICONFLOW_API_KEY
   ```

2. **网络连接失败**
   ```
   错误: Connection timeout
   解决: 检查网络连接和API服务状态
   ```

3. **模型维度不匹配**
   ```
   错误: 嵌入维度不匹配
   解决: 确认配置文件中的dimension与实际模型一致
   ```

4. **重排序服务不可用**
   ```
   错误: 重排序服务未配置
   解决: 配置reranker_provider或使用无重排序模式
   ```

## 依赖项

```
# Core AI/ML
langchain>=0.1.0
langchain-openai>=0.1.0
langchain-community>=0.1.0
transformers>=4.30.0
sentence-transformers>=2.2.0

# Data processing
numpy>=1.24.0
```

## 文件结构

```
grag/model/
├── __init__.py           # 包导出
├── llm_client.py         # LLM客户端
├── embedding_client.py   # 嵌入客户端
├── reranker_client.py    # 重排序客户端
├── vision_client.py      # 视觉/OCR客户端
├── model_manager.py      # 已移除（保留为 stub，用于提示旧 import 迁移）
└── README.md            # 本文档
```

## 扩展指南

### 添加新的LLM提供商

1. 在 `grag_config.yaml` 中添加提供商配置
2. 在 `LLMClient._create_model()` 中添加处理逻辑
3. 更新文档

### 添加新的嵌入提供商

1. 在配置中添加提供商
2. 在 `EmbeddingClient._create_embeddings()` 中实现
3. 处理维度验证

### 自定义重排序逻辑

1. 扩展 `RerankerClient` 类
2. 实现自定义重排序算法
3. 集成到模型管理器

## 最佳实践

1. **环境变量管理**: 使用环境变量管理敏感信息
2. **连接测试**: 启动时测试所有模型连接
3. **错误处理**: 实现完善的错误处理和降级策略
4. **资源管理**: 适当清理不需要的模型实例
5. **配置验证**: 启动前验证所有配置的正确性
6. **监控告警**: 监控模型性能和错误率