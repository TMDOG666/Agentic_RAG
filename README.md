# Agentic RAG

一个把 Agent 决策、RAG 检索、知识图谱和可视化工作台放在一起的实验型项目。

项目目标不是把检索流程写死，而是让 Agent 根据问题类型、证据需求和推理复杂度，自主选择检索方式、决定是否做多步检索，并尽量返回带证据的回答。

## 当前进度

截至 2026-04-16，仓库已经推进到下面这几个方向：

- Agent 检索计划已经沉到独立模块，支持 schema 暴露、计划解析、统一执行、结果归一化和去重。
- Agent 运行时更稳了，`agent_config.yaml` 支持从 `config/agent_config.yaml` 自动解析，不再强依赖单一路径。
- Skill 脚本参数解析做了修正，带引号的查询参数不会再被简单 `split()` 错切。
- 模型配置扩展到了云端和本地 OpenAI 兼容接口，当前默认配置偏向 `MiniMax + vLLM`，也补充了 `LM Studio`、`Ollama` 等入口。
- Graph 构建链路和 reranker 相关代码还在持续迭代，这部分已经有明显更新，但仍属于持续打磨区。
- WebUI 已经从简单页面升级成统一工作台，覆盖分组管理、文档入库、任务追踪、日志查看、图谱查看、实体 CRUD、Agent 对话和内嵌 API 文档。
- 新增了 `start_dev.bat`，本地联调可以一键拉起前后端。

## 现在能做什么

- 按 `group` 管理知识库。
- 文本录入或文件上传触发入库。
- 跟踪入库任务状态和后端日志。
- 查看分组图谱，并按 `doc_id` 过滤。
- 对 Postgres 中的实体做增删改查。
- 在分组级或文档级范围内和 Agent 对话。
- 通过 Agent tool 执行多种检索模式。

当前内置的检索模式包括：

- `chunks_vector`
- `chunks_keyword`
- `entities`
- `relations`
- `relations_by_entities`
- `entities_by_relations`

当前 Agent 侧暴露的核心工具包括：

- `load_skill`
- `read_skill_file`
- `execute_skill_script`
- `get_retrieval_plan_schema`
- `run_retrieval_plan`

## WebUI 工作台

现在的前端已经不只是一个演示页，主要有这几块：

- 分组总览页：支持创建、编辑、删除、进入分组。
- 分组工作台：按标签页组织文档、图谱和 Agent。
- 文档页：支持文本录入、文件上传、重建、任务轮询、日志筛选。
- 图谱页：支持 Neo4j 图谱展示和实体列表 CRUD。
- Agent 页：支持按分组或文档发问，并在浏览器本地保留会话历史。
- API Docs 页：可直接在前端里嵌入查看 FastAPI `/docs`。

## 项目结构

```text
.
|-- api/             FastAPI 接口层
|-- agent/           Agent runtime、LangGraph、tools、skills
|-- config/          Agent 和 GraphRAG 配置
|-- grag/            GraphRAG、图构建、检索、模型适配
|-- webui/           Vue 3 + Element Plus 前端工作台
|-- data/            本地数据目录
|-- test/            测试
|-- start_dev.bat    本地联调启动脚本
`-- README.md
```

## 快速启动

### 1. 安装依赖

后端：

```bash
pip install -r requirements.txt
```

前端：

```bash
cd webui
npm install
```

### 2. 配置模型

Agent 配置：

- `config/agent_config.yaml`

GraphRAG 配置：

- `config/grag_config.yaml`

至少准备下面这些环境变量中的一部分：

```powershell
$env:MINIMAX_API_KEY="your_key"
$env:SILICONFLOW_API_KEY="your_key"
$env:OPENAI_API_KEY="your_key"
```

如果你使用本地 OpenAI 兼容服务，例如 `vLLM`、`LM Studio`、`Ollama`，通常只需要保证本地服务端口和配置文件一致。

### 3. 启动后端

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

接口文档默认在：

- [Swagger UI](http://127.0.0.1:8080/docs)

### 4. 启动前端

```bash
cd webui
npm run dev
```

默认地址通常是：

- `http://127.0.0.1:5173`

### 5. 一键联调

Windows 下也可以直接运行：

```bat
start_dev.bat
```

这个脚本会尝试：

- 启动 FastAPI 后端
- 启动 WebUI 前端

## Agent 设计要点

当前这版实现里，职责大致是这样分的：

- Skill 负责描述方法和使用时机。
- Tool 层负责把底层能力包装成 Agent 可调用接口。
- Retrieval Plan 模块负责多步检索计划的 schema、校验、执行和结果归一化。
- LangGraph 负责 `agent -> tools -> agent` 的循环。
- Agent 本身负责判断是否要检索、如何组合检索、何时回到证据组织答案。

这意味着项目在方向上更偏向“Agent 决策检索”，而不是“预先写死检索流程”。

## 当前建议关注的入口

- `agent/adapter/runtime.py`
- `agent/adapter/graph.py`
- `agent/tools/retrieval_plan.py`
- `agent/tools/skill_tools.py`
- `agent/skill/manager.py`
- `config/agent_config.yaml`
- `config/grag_config.yaml`
- `webui/src/views/`

## 说明

- 这是一个还在快速迭代中的项目，README 会优先反映“当前代码已经做到的事”，不写太多远期规划。
- `webui/dist/` 是构建产物，前端源码以 `webui/src/` 为准。
- 如果你发现 README 和代码行为不一致，优先以 `config/` 和实际接口为准。

## 参考

- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [Agent Skills](https://agentskills.io/)
