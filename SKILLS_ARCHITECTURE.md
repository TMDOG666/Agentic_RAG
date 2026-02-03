# Agent Skills 运行机制与代码架构（本仓库）

本文档从代码架构角度解释本仓库 `agent_with_skills.py` 中 Skills 的发现、加载、调用与执行流程。

## 1. 总体结构

- **入口**

  - `agent_with_skills.py` 中的 `main()` 提供命令行交互循环
  - `run_once(user_text)` 用于把一次用户输入交给 LangGraph 工作流执行
- **核心组件**

  - **SkillManager**：负责 Skills 的扫描（元数据）、加载（指令/资源）、脚本执行
  - **LangGraph 工作流**：`agent_node`(LLM 决策) ↔ `ToolNode`(执行工具)
  - **工具（Tools）**：把 SkillManager 的能力包装成 LLM 可调用的函数（function calling）
- **Skills 目录约定**

  - 默认目录：`.cursor/skills/`
  - 每个 skill 是一个子目录：`.cursor/skills/<skill-name>/`
  - 必须存在 `SKILL.md`

## 2. Skills 的“三层渐进式加载”

本实现采用与 Agent Skills 标准一致的渐进式加载思想：

- **Level 1：发现（Discovery）**

  - 启动时仅读取每个 `SKILL.md` 的 YAML frontmatter（`name` + `description`）
  - 目的：让模型“知道有哪些技能可用”，但不把全部指令塞进上下文
- **Level 2：指令加载（Instructions Loading）**

  - 当模型判断某个技能与当前请求相关，会调用工具 `load_skill(skill_name)`
  - 返回该技能 `SKILL.md` 去除 YAML frontmatter 的正文部分
- **Level 3：资源加载（Resource Access）**

  - 当 `SKILL.md` 中提到需要进一步资料（例如 `[[formal-greetings.md]]`）时
  - 模型调用 `read_skill_file(skill_name, filename)` 读取该文件
  - 当 `SKILL.md` 指导执行脚本时
  - 模型调用 `execute_skill_script(skill_name, script_name, ...)`

## 3. 关键类：SkillManager

`SkillManager` 是 Skills 运行机制的“权威逻辑”。

### 3.1 初始化与扫描（Level 1）

- **构造**：`SkillManager(skills_dir: str = ".cursor/skills")`
- **扫描入口**：`self._scan_skills()`
- **扫描逻辑**：
  - 遍历 `skills_dir` 下的每个子目录
  - 发现 `SKILL.md` 后解析 YAML frontmatter
  - 把需要的元数据存入 `self.skills_metadata`

元数据结构（简化）：

- `skills_metadata[name] = {`
  - `description`: frontmatter 的 `description`
  - `path`: skill 目录路径
  - `skill_file`: `SKILL.md` 文件路径
- `}`

### 3.2 解析 frontmatter：`_parse_metadata()`

- 要求 `SKILL.md` 必须以 `---` 开头
- 使用 `content.split('---', 2)` 切分 `frontmatter` 与 `body`
- 用 `yaml.safe_load(parts[1])` 解析 YAML

### 3.3 加载技能正文（Level 2）：`load_skill(skill_name)`

- 根据 `skill_name` 找到 `skill_file`
- 读取 `SKILL.md`
- 若以 `---` 开头，则返回 `parts[2].strip()`（也就是正文）

### 3.4 读取技能文件（Level 3）：`read_skill_file(skill_name, filename)`

- 在 `skills_metadata[skill_name]['path']` 下拼出 `file_path`
- 文件存在则直接读取并返回

### 3.5 执行技能脚本：`execute_skill_script(skill_name, script_name, args="")`

- 根据扩展名选择执行器：
  - `.py`：`python <script_path>`
  - `.sh`：`bash <script_path>`
- 参数：把 `args` 做 `split()` 后追加到命令行
- 执行：`subprocess.run(..., capture_output=True, text=True, timeout=30, cwd=Path.cwd())`
  - `cwd=Path.cwd()` 的目的：让用户传入的相对路径（例如 `test_data.csv`）能从项目根目录解析

## 4. 工具层（Tools）：让模型“可调用”

在 `agent_with_skills.py` 中，以下函数用 `@tool` 装饰，成为 LLM 可调用的工具：

- `load_skill(skill_name: str) -> str`
- `read_skill_file(skill_name: str, filename: str) -> str`
- `execute_skill_script(skill_name: str, script_name: str, args: str = "", script_args: str = "") -> str`

说明：

- `execute_skill_script` 同时兼容 `args` 与 `script_args` 两种字段名
  - 这是为了兼容不同模型/提示词可能产生的参数名

工具列表在 `TOOLS = [...]` 中注册，然后在 `agent_node` 里通过 `MODEL.bind_tools(TOOLS)` 绑定给模型。

## 5. LangGraph 工作流：模型决策 ↔ 工具执行

### 5.1 节点

- **agent 节点**：`agent_node(state)`

  - 输入：`MessagesState`（历史对话消息）
  - 输出：模型返回的 message（可能包含 `tool_calls`）
- **tools 节点**：`ToolNode(TOOLS)`

  - 输入：模型产生的 tool_calls
  - 输出：工具执行结果消息

### 5.2 边与循环

- `START -> agent`
- `agent -> (conditional)`
  - 若模型 message 里有 `tool_calls`：`agent -> tools`
  - 否则：`agent -> END`
- `tools -> agent`（把工具执行结果再交给模型，让模型生成最终自然语言回复）

这意味着一次用户请求可能会经历：

1. 模型先决定“是否需要工具”
2. 如果需要，调用工具
3. 工具返回后模型再继续推理
4. 直到没有 tool_calls 为止

## 6. Skills 运行链路示例：分析 `test_data.csv`

用户输入：

- “帮我分析一下 test_data.csv”

典型流程：

1. **agent_node**：模型读取系统提示词与对话
2. 模型根据 `SkillManager` 扫描到的元数据，决定该请求命中 `data-analysis`
3. 模型发起 tool call：`load_skill(skill_name="data-analysis")`
4. **tools** 节点执行 `load_skill`，返回 `data-analysis/SKILL.md` 正文
5. 模型阅读技能正文后，按技能指令再发起 tool call：
   - `execute_skill_script(skill_name="data-analysis", script_name="analyze.py", args="test_data.csv")`
6. **tools** 节点执行脚本，返回脚本 stdout
7. 模型解读脚本输出，组织为用户可读的分析总结

## 7. 常见故障点（与排查思路）

- **工具参数名不一致**

  - 现象：工具调用阶段报参数校验错误
  - 例：技能文档/模型生成 `args`，但工具只接受 `script_args`
  - 处理：工具函数签名兼容不同字段名（本仓库已对 `execute_skill_script` 做兼容）
- **路径包含空格导致参数被 split() 拆错**

  - 现象：脚本收到的参数不完整，提示文件不存在
  - 原因：`args.split()` 按空格拆分
  - 处理：优先传递不含空格路径；或改造为更安全的参数传递（例如列表参数）
- **脚本依赖缺失**

  - 现象：`analyze.py` 导入 `pandas` 失败
  - 处理：安装依赖（或使用 `run.bat` 自动检查安装）
- **API Key / 模型调用失败**

  - 现象：`agent_node` 报认证/网络错误
  - 处理：检查 `SILICONFLOW_API_KEY` 与 `SILICONFLOW_BASE_URL`

## 8. 如何新增一个 Skill（与代码如何“识别它”）

1. 创建目录：`.cursor/skills/<skill-name>/`
2. 创建 `SKILL.md`，包含 YAML frontmatter：

```markdown
---
name: <skill-name>
description: <用一句话说明何时用这个技能 + 关键词>
---

# 标题

## 何时使用
...

## 步骤
1. ...
```

3. （可选）加入脚本/参考资料：

- `scripts/`：脚本
- `references/`：参考文档
- `assets/`：模板与资源

4. 重启程序

- SkillManager 在启动时扫描目录，因此新增 skill 后需要重启才能被发现
