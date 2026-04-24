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

## 未来软件大方向

这个项目后续不会只停留在“一个能跑的 Agentic GraphRAG Demo”，而是会沿着“可扩展、可恢复、可观测、可自演进”的方向继续推进，逐步把现在的实验性能力沉淀成一套更稳定的软件系统。

### 1. 从实验型 Demo 走向工程化 Agent 平台

- 继续统一 Agent、Tool、Skill、Ingestion 的运行时 schema，减少链路之间的隐式耦合。
- 把 trace、invocation、checkpoint、token、latency、error 全部对齐到统一事件模型，降低调试和前端消费成本。
- 让 Agent 运行时、知识入库链路、可视化工作台使用同一套状态表达，而不是各自维护一套“局部真相”。

### 2. 从固定知识库走向大规模知识资产系统

- 持续优化大文档、长文档、批量文档的流式入库能力，目标是支撑百万 token 级知识资产的分批构建与恢复。
- 让基础检索、图谱构建、知识融合解耦，保证即使图谱阶段失败，基础向量/关键词检索仍然可用。
- 强化 chunk 级、文档级、任务级 checkpoint，使长链路任务具备真正的续跑、重试、恢复能力。

### 3. 从“内置技能”走向通用 Skill 生态

- 继续推进 Skill Manifest 标准化，让 skill 的元数据、权限、入口、依赖、运行方式都可以被统一装载和校验。
- 保持“tool 层做通用能力、skill 层做业务扩展”的边界，方便后续接入用户自定义业务 skill。
- 为后续的 skill marketplace、跨项目 skill 复用、MCP/外部工具接入预留标准接口。

### 4. 从“能回答问题”走向可验证的决策检索系统

- 继续强化 Agent 对检索模式的自主决策能力，不把检索意图写死在关键词规则里。
- 支持更复杂的多步检索与推理链，把向量检索、关键词检索、图检索、关系扩展、重排序组合成可验证的计划执行过程。
- 让最终回答尽量附带引用证据、任务轨迹和过程可回放信息，提高可解释性和可信度。

### 5. 从“能运行”走向可量化评估

- 建立更系统的 RAG 评估集与压测流程，持续评估召回率、准确率、F1-score、时延、token 消耗与失败率。
- 对不同 provider、本地模型、重排序模型、embedding 模型建立横向对比，减少“配置改了但效果不可知”的问题。
- 把评估、观测、回放、恢复结合起来，让系统具备持续优化和半自动演进能力。

### 6. 从单机项目走向长期演进的软件形态

- 进一步拆分配置系统、任务系统、Graph 构建系统、Agent Runtime，收紧模块边界，降低维护成本。
- 让前后端都围绕统一 DTO 和统一状态机演进，而不是依赖零散字段拼接页面。
- 逐步补齐测试、迁移脚本、配置校验和异常恢复机制，让项目更适合作为长期维护的软件底座。

## 说明

- 这是一个还在快速迭代中的项目，README 会优先反映“当前代码已经做到的事”，未来方向部分只描述明确的演进主线，不写空泛路线图。
- `webui/dist/` 是构建产物，前端源码以 `webui/src/` 为准。
- 如果你发现 README 和代码行为不一致，优先以 `config/` 和实际接口为准。

## 参考

- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [Agent Skills](https://agentskills.io/)
