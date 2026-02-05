---
name: event-aggregation
description: 将逐句事件抽取结果进行文档级汇总：合并同一事件的多句描述、统一指代后的实体名称、生成 document_events 与 entities，输出结构化 JSON。
---

# 文档级事件汇总（Aggregation）

## 目标
把逐句事件抽取结果汇总为文档级结构：

1. 合并重复/同指事件（同一触发、同一参与者、同一时间地点等）。
2. 尽量统一实体名称（例如“公司”“该公司”“某企业”统一为已解析的名字；如果没有明确名字则保持原样）。
3. 输出 document-level 的事件列表与实体列表。

## 输入
用户会提供：

- `resolved_text`（可选）
- `sentences`（可选）
- `sentence_events`: 数组（每个元素是 `event-extraction-srl` 的输出）

## 输出（必须严格只输出 JSON）
输出一个 JSON object：

- `entities`: 数组
  - `entity_id`: `ent1`, `ent2`, ...
  - `name`
  - `aliases`: 数组
- `document_events`: 数组
  - `event_id`: `ev1`, `ev2`, ...
  - `type`
  - `trigger_texts`: 数组（该事件在文档中出现过的触发词/短语）
  - `roles`: 同 `event-extraction-srl` 的 roles 结构（值为数组）
  - `evidence_sentence_ids`: 该事件来自哪些句子（如 `["s1","s3"]`）

约束：

- **只输出 JSON，不要 Markdown，不要解释文字**。
- 如果无法判断是否同一事件：宁可不合并。
