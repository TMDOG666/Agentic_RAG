---
name: rag-answering
description: 基于 RAG 检索结果进行证据精选与总结，并在引用（文档名+chunk_id）支撑下生成最终答案；强制先精选再回答，减少幻觉。
---

# RAG Answering（检索后精选总结并回答）

## 目标

当用户的问题需要依赖知识库内容回答时：

1. 使用 `rag-retrieval` 技能执行检索
2. 对检索结果做证据“精选/去重/压缩”
3. 先输出“证据摘要”，再输出“最终答案”
4. 最终答案必须给出引用：**文档名 + chunk_id**

## 输入

你将从对话上下文中获得：

- 用户问题（自然语言）
- `[RAG_CONTEXT] group_id=...`（必需）
- `[RAG_CONTEXT] doc_id=...`（可选）

如果缺少 `group_id`：你必须先向用户追问或提示调用方补齐，而不是盲目回答。

## 强制流程（必须严格按顺序执行）

### Step 1：决定检索策略（按问题类型）

- **事实问答 / 摘要 / 解释某一主题**：
  - 先 `chunks_vector`
  - 若结果为空或明显偏离，再 `chunks_keyword`

- **包含专有名词、章节名、字段名、固定短语**：
  - 先 `chunks_keyword`
  - 再用 `chunks_vector` 补充

- **列举实体（有哪些公司/产品/机构/人物）**：
  - 先 `entities`
  - 若需要原文证据：用实体名回到 `chunks_vector/chunks_keyword`

- **关系/结构问题（X 与 Y 的关系、上下游、组成、隶属、主营业务链条）**：
  - 先 `relations`
  - 需要扩展时再 `relations_by_entities` / `entities_by_relations`
  - 最后回到 `chunks_vector/chunks_keyword` 找原文证据

### Step 2：执行检索（调用 rag-retrieval）

你必须先调用工具加载检索技能并执行脚本：

1. `load_skill("rag-retrieval")`
2. `execute_skill_script(...)` 执行对应脚本

参数要求：

- 你必须从 `[RAG_CONTEXT]` 中解析 `group_id`（以及可选 `doc_id`）
- 传参时始终包含：
  - `--group-id <group_id>`
- 若存在 doc_id，则额外包含：
  - `--doc-id <doc_id>`

### Step 3：解析返回 JSON 并抽取候选证据

检索脚本会输出 JSON（来自 `POST /retrieval`）。你需要从中抽取“候选证据条目”。

候选证据条目应尽量包含以下字段（若不存在则留空/用替代字段）：

- `document_name`（或 `doc_name`/`doc_title`，若都没有则用 `doc_id` 代替）
- `chunk_id`
- `text`（或 `content`/`chunk_text`）
- `score`（若有）

注意：不同 mode 返回结构可能不同。若你无法定位字段：

- 优先在 JSON 中搜索最像 chunk 文本的字段（长文本字段）
- 仍不确定则改用 `chunks_vector` 或 `chunks_keyword` 再检索一次

### Step 4：证据去重与精选（必须做）

- 去重：
  - 完全相同文本去重
  - 高重叠文本（开头/结尾高度相似）保留 score 更高或信息量更大的

- 精选：
  - 默认选择 3-8 条证据
  - 每条证据文本建议截断到 200-400 字（保留关键句）

### Step 5：先输出“证据摘要”，再输出“最终答案”（必须）

你必须按如下结构输出：

1. `证据精选（Top N）`
   - 每条包含：
     - `引用ID`（从 1 开始）
     - `document_name`
     - `chunk_id`
     - `原文摘录`（截断后的关键片段）

2. `证据摘要`
   - 用 3-8 条 bullet 总结证据要点
   - 每条 bullet 必须标注引用：例如 `[1][3]`

3. `最终答案`
   - 只基于证据摘要与引用回答
   - 对每个关键结论标注引用，例如 `...（见[2][5]）`
   - 如果证据不足以支撑某个结论，必须明确说明“不确定/未检索到证据”，并建议补充检索关键词或确认 doc_id

## 输出格式（必须严格遵循）

- 证据精选（Top N）
  1) document_name=<...> chunk_id=<...>
     excerpt: <...>
  2) ...

- 证据摘要
  - ... [1][2]
  - ... [3]

- 最终答案
  <自然语言回答，带引用>
