---
name: rag-retrieval
description: 为 Agent 提供 RAG 检索能力：根据用户问题选择合适的检索模式（chunks/entities/relations/graph primitives）并组合调用，返回可用于回答的证据片段。
---

# RAG Retrieval（面向 Agent 的检索技能）

## 目标

在你需要基于知识库回答问题时，调用本技能完成检索：

- 在正确的 `group_id`（以及可选 `doc_id`）范围内检索
- 选择合适的检索模式或组合（chunk 召回、实体/关系召回、图扩展）
- 输出可用于最终回答的“证据”（chunks 文本、实体名、关系三元组等）

本技能对齐的底层接口：

- API 统一入口：`POST /retrieval`（由 `api.services.retrieval_service.RetrievalService` 分发）
- GRAG Facade：`grag/entrypoint.py` 中的 `GRAG` 类方法

## 输入约定（重要）

- `group_id`：必须存在，用于数据隔离。
- `doc_id`：可选，若用户明确只问某篇文档，再传入以做过滤。

在本项目中，`group_id/doc_id` 推荐由 API 层注入到对话文本中：

- `[RAG_CONTEXT] group_id=...`
- `[RAG_CONTEXT] doc_id=...`（可选）

当你需要检索时：

1. 从对话上下文中读取当前的 `group_id`（以及可选 `doc_id`）。
2. 决定检索模式与组合。
3. 通过本技能提供的脚本执行检索（`execute_skill_script`）。

## 如何调用（执行脚本）

你需要使用工具：

- `execute_skill_script(skill_name="rag-retrieval", script_name="scripts/<script>.py", args="...")`

脚本参数统一使用：

- `--group-id <group_id>`
- `--doc-id <doc_id>`（可选，不限制为空）

## 检索模式与参数

下述 6 种模式均由 `GRAG` 暴露，并由 `RetrievalService` 对应的 mode 触发。

### 1) chunks_vector（向量召回 chunks）

适用：

- 用户问题是“找某个主题/段落/事实依据”，需要原文片段支撑
- 同义改写较多，关键词不稳定

参数：

- 必填：
  - `group_id`
  - `query`
- 常用可选：
  - `top_k`（默认 5-20）
  - `doc_id`
  - `doc_time_start` / `doc_time_end`

脚本：

- `scripts/chunks_vector.py`

示例 args：

- `--group-id <gid> --query 主营业务 是什么 --top-k 5`

### 2) chunks_keyword（关键词召回 chunks）

适用：

- 用户问题包含明确关键词（专有名词、章节名、表格字段名）
- 需要精确包含某些词（例如“审计意见”“关联交易”）

参数：

- 必填：
  - `group_id`
  - `query`
- 常用可选：
  - `top_k`
  - `doc_id`

脚本：

- `scripts/chunks_keyword.py`

### 3) entities（实体向量检索）

适用：

- 用户在问“有哪些公司/人物/产品/机构/指标”
- 需要先找到实体候选，再用实体去扩展关系或回到 chunks

参数：

- 必填：
  - `group_id`
  - `query`
- 常用可选：
  - `top_k`
  - `doc_id`
  - `output_fields`（字段白名单）

脚本：

- `scripts/entities.py`

### 4) relations（关系向量检索）

适用：

- 用户在问“X 和 Y 什么关系”“X 的主营业务/子公司/供应商/客户”
- 需要先召回关系三元组候选，再做图扩展或回到 chunks 验证

参数：

- 必填：
  - `group_id`
  - `query`
- 常用可选：
  - `top_k`
  - `doc_id`
  - `output_fields`

脚本：

- `scripts/relations.py`

### 5) relations_by_entities（Neo4j primitives：给定实体名查关系）

适用：

- 已经有实体名列表（来自 `entities`，或用户明确给出）
- 需要结构化地扩展 1-hop 关系，用于回答“相关方/上下游/隶属/组成”等

参数：

- 必填：
  - `group_id`
  - `entity_names`（列表）
- 常用可选：
  - `limit`（默认 50-200）
  - `doc_id`

脚本：

- `scripts/relations_by_entities.py`

### 6) entities_by_relations（Neo4j primitives：给定关系查实体）

适用：

- 已有关系候选（来自 `relations` 或 `relations_by_entities`）
- 需要反查与这些关系相连的实体（用于汇总“涉及哪些主体”）

参数：

- 必填：
  - `group_id`
- 二选一：
  - `relation_ids`（列表）
  - `relation_triples`（JSON 列表，元素为 dict）
- 常用可选：
  - `limit`
  - `doc_id`

脚本：

- `scripts/entities_by_relations.py`

## 组合检索策略（如何根据问题选模式）

你需要根据用户问题类型选择组合。推荐策略如下：

### A) 事实问答 / 摘要类（需要原文证据）

- 首选：`chunks_vector`
- 兜底：`chunks_keyword`

输出：

- 选出最相关的 3-8 个 chunk 文本作为证据，再组织答案。

### B) 专有名词/章节/字段精确匹配

- 首选：`chunks_keyword`
- 补充：`chunks_vector`

### C) “有哪些/列举/实体集合”问题

- 先：`entities`（得到实体候选）
- 再：
  - 若用户还问关系：对这些实体做 `relations_by_entities`
  - 若用户还问原文证据：用实体名作为 query 回到 `chunks_vector` 或 `chunks_keyword`

### D) “关系/结构/上下游/隶属/股权/主营业务”问题

- 先：`relations`（召回关系候选）
- 再：
  - 用 `relations_by_entities` 扩展关键实体的 1-hop 关系
  - 必要时用 `entities_by_relations` 汇总相关实体
- 最后：用关键实体/关系关键词回到 `chunks_vector/chunks_keyword` 找证据片段（避免只输出结构化结果没有出处）

## 输出要求（给最终回答用）

- 最终回答前，你应当从检索结果中提取：
  - chunks：可直接引用的文本片段（并尽量保留 chunk_id / doc_id 若返回里有）
  - entities：实体名（canonical_name/name）
  - relations：relation_id 或关系三元组字段（若返回里有）

- 如果检索结果为空：
  - 降级切换模式（vector <-> keyword，或 entity/relations -> chunks）
  - 仍为空则向用户澄清：是否选错了 group/doc，或需要更具体关键词
