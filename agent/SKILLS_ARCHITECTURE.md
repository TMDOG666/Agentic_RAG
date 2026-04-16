# Agent Skills 架构说明

本文档描述本仓库里 Agent、Tools、Skills 三层是如何协作的。

## 分层

从高到低分别是：

- `agent/app/`
  - 业务应用层示例
- `agent/agent/`
  - Agent 对外入口，例如 `run_once()` 和 CLI
- `agent/adapter/`
  - runtime 组装与 LangGraph 工作流
- `agent/tools/`
  - function calling 工具层
- `agent/skill/`
  - SkillManager、registry、skill 资源访问与脚本执行
- `agent/llm/`
  - 模型配置与实例化

## 当前技能运行方式

### Level 1：发现

启动时由 `SkillManager` 扫描 skills 目录，只读取每个 `SKILL.md` 的：

- `name`
- `description`

目的是让模型先知道有哪些技能，而不是一开始就把全部 skill 正文塞进上下文。

### Level 2：加载

当模型判断某个 skill 相关时，通过：

- `load_skill(skill_name)`

加载该 skill 的正文说明。

### Level 3：资源访问与脚本执行

当 skill 需要读取附加资料或执行脚本时，通过：

- `read_skill_file(skill_name, filename)`
- `execute_skill_script(skill_name, script_name, args)`

## Tool 层职责

当前 tool 层不再只是一组被动包装，而是承载了一部分运行时模块能力。

### 基础工具

- `load_skill`
- `read_skill_file`
- `execute_skill_script`

### 检索计划模块

检索计划能力已经从 skill 文本中抽离，模块化到 tool 层：

- schema
- plan 解析
- 参数校验
- 多步执行
- 结果归一化
- 证据去重

对应文件：

- [retrieval_plan.py](/G:/Agentic_RAG/agent/tools/retrieval_plan.py)
- [skill_tools.py](/G:/Agentic_RAG/agent/tools/skill_tools.py)

暴露工具：

- `get_retrieval_plan_schema()`
- `run_retrieval_plan(query, plan_json, group_id, doc_id)`

## 为什么把 plan 放到 tool 层

因为 `plan` 更像 Agent 的运行时执行模块，而不是 skill 的知识文本。

这样做的好处是：

- skill 专注方法论
- tool 专注稳定执行
- Agent 负责决策
- 后续更容易扩展用户自定义业务 skill

## 当前 RAG 调用链

推荐调用顺序：

1. Agent 先加载 `rag-retrieval` 或 `rag-answering`
2. Agent 自己判断问题需要什么检索结构
3. 如有需要先获取检索计划 schema
4. Agent 组织 `plan_json`
5. `run_retrieval_plan(...)` 执行
6. Agent 基于 `items` 和 `steps` 结果回答

## 检索计划模块输出

当前统一输出：

- `plan`
- `steps`
- `items`
- `errors`

其中：

- `steps` 表示每一步检索实际执行情况
- `items` 表示归一化后的证据集合
- `errors` 表示执行中的异常或失败步骤

## SkillManager 说明

`SkillManager` 负责：

- 发现 skill
- 加载 skill 正文
- 读取 references/assets
- 执行 skill 脚本

另外当前已经修复一个稳定性问题：

- 脚本参数解析从 `split()` 改成 `shlex.split()`
- 避免带空格或带引号的 query 被错误拆分

## 适合未来扩展的方向

- 将 retrieval plan 继续拆分成 `schema / executor / normalizer`
- 为业务 skill 增加可复用的 tool 模块
- 为复杂问答增加 evidence ranking / validation 模块
- 将引用输出格式进一步标准化
