---
name: rag-retrieval
description: 为 Agent 提供多模式 RAG 检索能力。你负责判断问题需要哪些检索模式、是否需要多步组合与验证，再调用 tool 层的检索计划模块执行。
---

# RAG Retrieval

## 目标

当你需要基于知识库回答问题时，不要把检索理解成“只选一个模式”。

你需要先判断：

- 这是事实定位、精确匹配、实体枚举、关系分析，还是多跳推理
- 是否需要多种检索模式组合
- 是否需要把结构化结果再回查到原文 chunk 做验证
- 最终回答是否需要可引用的证据

## 可用检索模式

- `chunks_vector`
- `chunks_keyword`
- `entities`
- `relations`
- `relations_by_entities`
- `entities_by_relations`

## 你的职责

### 1. 先判断检索结构

你要自己判断：

- 单步检索还是多步检索
- 先实体还是先关系
- 是否需要验证回查
- 哪一步是召回，哪一步是验证

不要把问题类型判断交给硬编码规则。

### 2. 再调用 tool 层的检索计划模块

检索计划是 Agent/tool 层能力，不属于 skill 本体。

当你准备执行时：

1. 如有需要，先调用 `get_retrieval_plan_schema()`
2. 按 schema 组织 `plan_json`
3. 调用 `run_retrieval_plan(query, plan_json, group_id, doc_id)`

### 3. 证据优先

如果你拿到的是实体或关系候选，而最终回答需要可靠引用，应继续增加验证步骤，回查 chunk 证据。

不要只凭结构化召回直接下结论。

## 常见组合方式

### 事实问答

- 先 `chunks_vector`
- 必要时补 `chunks_keyword`

### 精确术语 / 字段 / 条款定位

- 先 `chunks_keyword`
- 必要时补 `chunks_vector`

### 实体枚举

- 先 `entities`
- 如需原文证据，再回查 `chunks_vector` 或 `chunks_keyword`

### 关系分析

- 先 `relations`
- 需要扩展时用 `relations_by_entities` / `entities_by_relations`
- 需要引用时再回查 `chunks_vector` 或 `chunks_keyword`

### 多跳推理

常见链路：

1. `entities`
2. `relations_by_entities`
3. `entities_by_relations`
4. `chunks_vector` / `chunks_keyword` 验证

## 输出要求

在拿到检索计划执行结果后，你要：

- 阅读每个 step 的结果
- 保留可引用证据
- 对重复证据去重
- 区分候选关系和已验证关系

如果证据不足，要明确说明不足发生在哪一步。
