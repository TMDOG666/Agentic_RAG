# Agentic RAG：由 Agent 决策检索模式的 GraphRAG 框架
 
 本项目目标：构建一个 **Agentic RAG / GraphRAG** 框架。
 
 核心思想：
 - **不把检索策略写死**（例如永远向量检索或永远关键词检索）
 - 把“用哪种检索模式”的选择权交给 **Agent**
 - Agent 通过 **Skills** 调用不同检索能力（Vector / Keyword / GraphRAG / Hybrid），拿到证据后再生成回答
 
 本仓库同时包含一条“图谱资产构建流水线”（`grag/graph_construction`）：把文档转成可用于 GraphRAG 的实体/关系中间产物（并完成文档内实体融合）。
 
 ---
 
 ## ✅ 已实现
 
 - **AgentSkills 三层渐进式加载机制**
   - Level 1：启动时仅加载 Skills 元数据（`name + description`），用于“让模型知道有哪些技能”
   - Level 2：按需 `load_skill()` 加载该技能完整指令（`SKILL.md` 正文）
   - Level 3：按需读取技能引用文件 / 执行技能脚本
 
 - **基于 LangGraph 的 Agent ↔ Tools 循环**
   - 模型在 `agent_node` 决策是否需要工具调用
   - `ToolNode` 执行工具（加载 skill / 读文件 / 执行脚本）并把结果回传给模型继续推理
 
 - **图谱资产构建流水线（文档级）**：`grag/graph_construction/graph_construction_manager.py`
   - 指代消解（Coreference Resolution）
   - 语义分块（Semantic Chunking）
   - 实体/关系抽取（LLM extraction）
   - raw 解析为结构化对象（Parser）
   - 文档内实体消歧 + 知识融合（Embedding + 聚类 + LLM 融合）
 
 ---
 
 ## 🎯 最终产物（你应该期待什么）
 
 在线问答时，Agent 会根据用户问题选择一种（或多种）检索技能：
 
 - **向量检索（Vector Retrieval）**：适合语义相似、表述不一致的问题
 - **关键词检索（Keyword/BM25 Retrieval）**：适合专有名词、编号、精确短语
 - **图检索（GraphRAG）**：适合关系链、多跳关联（1-2 hop）、因果/依赖关系问题
 - **混合检索（Hybrid Retrieval）**：向量 + 关键词 + 图扩展组合
 
 Agent 拿到技能返回的证据 chunks 后，再将证据组织成最终回答。
 
 ---
 
 ## 检索（Retrieval）与重排序（Rerank）用法（grag/retrieval）
 
 本仓库在 `grag/retrieval/` 下提供了一个统一检索入口 `RetrievalManager`，用于把三种基础检索模式封装成同一个 `search()`。
 
 ### 1) 三种检索模式
 
 - **keyword**：Postgres chunk 文本 ILIKE 匹配（适合专有名词/编号/精确短语）
 - **semantic**：Embedding + Milvus 向量检索（适合语义相似但表述不一致）
 - **graph**：Neo4j 实体子图扩展（适合关系链/多跳关联）
 
 共同约束：
 - **group_id 必填**：用于数据隔离。
 - chunk 类检索（keyword/semantic）支持可选 `doc_time_start/doc_time_end` 过滤。
 
 ### 2) 代码调用示例
 
 ```python
 from grag.retrieval import RetrievalManager
 
 rm = RetrievalManager()
 
 res = rm.search(
     group_id="group_001",
     query="智云科技 2024 年度报告",
     modes=["keyword", "semantic"],
     top_k=10,
     # 可选：按文档时间过滤（建议 ISO8601）
     doc_time_start="2026-01-01T00:00:00+00:00",
     doc_time_end="2026-12-31T23:59:59+00:00",
     # 可选：启用重排序（对 keyword/semantic 的 chunk 结果生效）
     rerank_enabled=True,
     # 可选：指定重排序 provider；None 表示用 grag_config.yaml 的默认 reranker_provider
     rerank_provider=None,
 )
 
 print(len(res.keyword_hits), len(res.semantic_hits))
 ```
 
 ### 3) 如何启用/切换重排序（rerank）
 
 重排序依赖 `grag_config.yaml` 的以下配置：
 
 - `reranker_provider`: 默认重排序提供商（可选）
 - `reranker_providers`: 提供商配置表（包含 model/base_url/api_key_env/top_k 等）
 
 你也可以用环境变量覆盖（优先级更高，详见 `grag/model/reranker_client.py`）：
 
 - `GRAG_RERANKER_PROVIDER`
 - `GRAG_RERANKER_MODEL`
 - `GRAG_RERANKER_BASE_URL`
 - `GRAG_RERANKER_API_KEY`
 
 注意：
 - **未配置 reranker 或调用失败时会自动降级**为原始顺序，保证检索主流程可用。
 - 当 `rerank_enabled=True` 时：
   - keyword/semantic：对 chunk 列表重排序
   - graph：对返回子图中的 `nodes` 列表重排序（`edges` 不变）

---
 
 ## 📁 项目结构（核心目录）
 
 ```
 .
 ├── README.md
 ├── agent_with_skills.py                # 兼容入口：转发到 agent/agent_with_skills.py
 ├── agent_config.yaml                   # 模型/Provider 配置（OpenAI-compatible）
 ├── agent/                              # Skills Agent 运行时（LangGraph + Tools + Skills）
 │   ├── SKILLS_ARCHITECTURE.md          # Skills 运行机制（建议先读）
 │   ├── agent/                          # 对外入口：run_once/CLI
 │   ├── adapter/                        # runtime 组装 + LangGraph 工作流
 │   ├── tools/                          # tool 封装（load_skill/read_skill_file/execute_skill_script）
 │   ├── skill/                          # SkillManager 权威逻辑（含 registry 缓存）
 │   └── app/                            # 应用层示例（多 skill 串联流水线）
 ├── grag/                               # GraphRAG 相关：图谱资产构建与（未来）图检索
 │   └── graph_construction/             # 文档→实体/关系→融合 的流水线
 └── .cursor/skills/                     # Skills 目录（可扩展）
     └── <skill-name>/
         ├── SKILL.md
         ├── scripts/...
         ├── references/...
         └── assets/...
 ```
 
 ---
 
 ## 🚀 快速开始
 
 ### 1) 安装依赖
 
 按你本机环境选择（conda/venv 均可）。以下仅示例：
 
 ```bash
 pip install langchain langchain-openai langgraph pyyaml
 ```
 
 如果你的 skills 脚本需要 `pandas` 等依赖，请按需安装。
 
 ### 2) 配置模型 Provider
 
 - 编辑 `agent_config.yaml` 选择 provider
 - 设置 API Key（示例以 siliconflow 为例）：
 
 ```bash
 # Windows PowerShell
 $env:SILICONFLOW_API_KEY="your_api_key_here"
 ```
 
 ### 3) 运行
 
 ```bash
 python agent_with_skills.py
 ```
 
 在 CLI 中输入：
 - `skills`：查看当前发现的技能
 - `debug`：开启调试（输出消息历史）
 
 ---
 
 ## 🧠 运行机制（简述）
 
 - **启动**：SkillManager 扫描 `.cursor/skills/`，把所有 skill 的 `name + description` 注入到 system prompt
 - **决策**：LLM 根据用户问题选择要调用的 skill
 - **执行**：LLM 通过工具
   - `load_skill(skill_name)` 获取指令
   - `read_skill_file(skill_name, filename)` 读取引用材料（仅允许 `references/` 与 `assets/`）
   - `execute_skill_script(skill_name, script_name, args=...)` 执行脚本得到确定性结果
 
 ---
 
 ## 🧩 如何实现“让 Agent 选择检索模式”（推荐做法）
 
 ### 1) 用多个检索 skill，而不是写死一个检索器
 
 推荐至少拆成：
 - `vector-retrieval`
 - `keyword-retrieval`
 - `graph-retrieval`
 - （可选）`hybrid-retrieval`
 
 每个 skill 的 `description` 要写清楚“何时使用”，让 agent 能可靠路由。
 
 ### 2) 建议检索 skill 的脚本输出统一为 JSON
 
 因为工具执行结果本质是 stdout 文本，为了稳定被 agent 消费，建议让脚本输出结构化 JSON，例如：
 
 ```json
 {
   "strategy": "vector",
   "query": "...",
   "results": [
     {"doc_name": "...", "chunk_id": "...", "score": 0.82, "text": "..."}
   ]
 }
 ```
 
 Agent 读取 `results[].text` 作为证据再组织最终回答。
 
 ---
 
 ## 🏗️ `grag/graph_construction` 在 GraphRAG 中的定位
 
 这部分是 **离线资产构建**：把文档加工成“图检索可用”的结构化中间产物。
 
 当前流水线产出已经覆盖：
 - 文档级融合实体：`canonical_name / aliases / type / description`
 - 文档级标准化关系：`subject/object` 已重写到 canonical
 
 后续若要把它真正变成可检索的 GraphRAG，需要在图检索 skill 中把这些产物落地为：
 - 可查询的 nodes/edges（JSON、本地 KV、或图数据库）
 - 实体 ↔ chunk/doc 的溯源索引（用于“沿图扩展后回到原文证据”）
 
 ---
 
 ## 📚 参考
 
 - Agent Skills: https://agentskills.io/
 - LangGraph: https://langchain-ai.github.io/langgraph/
