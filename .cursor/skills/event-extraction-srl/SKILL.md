---
name: event-extraction-srl
description: 面向通用领域的句子级事件抽取与题元/语义角色标注（施事者、受事者、触发词、主题、时间、地点等），输出统一 JSON schema。适用于新闻、报告、叙述文本等。
---

# 事件抽取 + 语义角色标注（通用 SRL）

## 目标
对单句进行事件抽取，并给每个事件标注通用语义角色（题元角色）。

## 输入
用户会提供：

- `sentence_id`
- `sentence`
- （可选）来自上一步的 `coref_map` 或 `resolved_text`，用于补全角色

## 事件定义（通用）
一个事件至少包含：

- **触发词（trigger）**：表达事件发生的核心谓词/动词或关键短语
- **事件类型（type）**：尽量选择一个粗粒度类型（如 `Communication`/`Transaction`/`Movement`/`Conflict`/`Creation`/`Destruction`/`StateChange`/`Other`）
- **角色（roles）**：
  - `agent`：施事者（做动作的主体）
  - `patient`：受事者（被动作影响的对象）
  - `theme`：主题/内容（例如“讨论的内容”“声明的内容”“发布的内容”）
  - `recipient`：接收者（说给谁/给谁转账/寄给谁）
  - `time`：时间
  - `location`：地点
  - `instrument`：工具/手段（可选）

## 输出（必须严格只输出 JSON）
输出一个 JSON object：

- `sentence_id`
- `sentence`
- `events`: 数组
  - `event_id`: 例如 `s3_e1`
  - `trigger`: { `text`: "..." }
  - `type`: 字符串
  - `roles`: object（键为 role 名，值为数组；没有则给空数组）
    - 每个 role element: { `text`: "..." }
  - `polarity`: `positive`/`negative`/`unknown`
  - `modality`: `asserted`/`hypothetical`/`desired`/`negated`/`unknown`
  - `evidence`: 从句子中截取的一小段证据文本（可选）

约束：

1. **只输出 JSON，不要 Markdown，不要解释文字**。
2. 一个句子可能有 0 个、1 个或多个事件。
3. 如果角色无法确定：对应数组为空。
4. 触发词必须来自原句（不要编造）。

## 实用启发

- 多动词句：按动词/谓词中心拆成多个事件。
- 名词性事件：如“签署协议”“发生事故”“发布声明”，触发词可以是动宾短语。
- 对被动句：受事者往往是语法主语，但语义角色仍需区分施事/受事。
