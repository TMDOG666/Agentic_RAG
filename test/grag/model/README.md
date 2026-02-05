# GraphRAG Model 层测试

本目录包含对 `grag.model` 的单元测试，风格与 `test/grag/config` 一致。

## 前置条件

- 已激活 conda 环境 **langchain**（含 `langchain-openai`、`langchain-community` 等）
- 项目根目录下存在 `config/grag_config.yaml` 且格式正确
- 不强制要求配置 API Key；部分测试仅验证初始化与配置读取，不发起真实请求

## 运行方式

在项目根目录 `G:\Agentic_RAG` 下执行：

```bash
# 激活环境后运行单个模块
conda activate langchain
python test/grag/model/test_llm_client.py
python test/grag/model/test_embedding_client.py
python test/grag/model/test_reranker_client.py
python test/grag/model/test_model_manager.py

# 运行全部 Model 测试
python test/grag/model/run_all_tests.py
```

或进入 test 目录后运行（需保证能 import grag）：

```bash
cd test/grag/model
python run_all_tests.py
```

## 测试模块说明

| 文件 | 说明 |
|------|------|
| `test_llm_client.py` | LLMClient 初始化、提供商信息、get_model 缓存、refresh、全局函数 |
| `test_embedding_client.py` | EmbeddingClient 初始化、get_embeddings、维度、refresh、全局函数 |
| `test_reranker_client.py` | RerankerClient 初始化、is_available、rerank 返回格式、全局函数 |
| `test_vision_client.py` | VisionClient 初始化、视觉模型配置校验、客户端懒加载、全局函数 |
| `test_model_manager.py` | ModelManager 初始化、各 get_*_client、model_info/status、refresh/cleanup、全局函数 |
| `run_all_tests.py` | 依次执行上述 5 个模块的 run_tests() 并汇总结果 |

## 与 Config 的联动

所有测试在 `setup_method` 或 `run_tests()` 前会调用 `grag.config.initialize_config()`，确保从 `config/grag_config.yaml` 加载配置后再创建 LLM/Embedding/Reranker 客户端与 ModelManager，从而验证「配置层 + model 层」的联动。
