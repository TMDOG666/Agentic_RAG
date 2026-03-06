---
name: time-now
description: 获取当前时间（默认 UTC ISO8601），用于为 agent/脚本提供 doc_time、日志时间戳或时间过滤参数。
---

# Time Now（获取当前时间）

## 适用场景

当你需要“当前时间”来构造参数或记录时间戳时使用本技能，例如：

- 为 ingestion/upload 构造 `doc_time`（建议 ISO8601）
- 为检索构造 `doc_time_start/doc_time_end`
- 生成日志时间戳

## 如何调用

使用工具 `execute_skill_script` 执行脚本：

- `execute_skill_script(skill_name="time-now", script_name="scripts/now.py", args="...")`

## 脚本与参数

### scripts/now.py

默认输出：UTC 的 ISO8601 时间戳（形如 `2026-03-05T07:12:34Z`）。

参数：

- `--utc`：输出 UTC 时间（默认开启；不传也等价于开启）
- `--local`：输出本地时区时间（带偏移，如 `+08:00`）
- `--format <fmt>`：自定义输出格式（Python `strftime` 格式）。若提供该参数，则不使用 ISO8601。

建议：

- ingestion 的 `doc_time` 推荐使用默认输出（UTC ISO8601）。
