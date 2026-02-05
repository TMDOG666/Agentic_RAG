# Skill 编写规范（本项目）

本项目的 Skills 采用 Agent Skills 格式（参考：
https://agentskills.io/specification
https://agentskills.io/what-are-skills
）。

该文档额外说明了**本项目当前实现的约束**（例如允许读取的资源目录白名单）。

## 1. 目录结构

本项目约定 skills 根目录为：

- `.cursor/skills/`

每个 skill 是其下的**一级子目录**（当前 `SkillManager` 只扫描一层，不递归）：

```text
.cursor/skills/
  <skill-name>/
    SKILL.md
    references/
    assets/
    scripts/
```

- `SKILL.md`：必需
- `references/`：可选（长文档、参考材料）
- `assets/`：可选（模板、样例数据、schema 等静态资源）
- `scripts/`：可选（可执行脚本）

## 2. 命名规范

### 2.1 skill 目录名

- 必须为：`a-z` / `0-9` / `-`
- 长度：1-64
- 不能以 `-` 开头或结尾
- 不能包含连续连字符 `--`

示例：

- `event-extraction-srl`
- `sentence-segmentation`

### 2.2 SKILL.md frontmatter 的 name

- `name` 必须与 skill 目录名**完全一致**
- 本项目启动扫描时会做校验，不一致会被跳过

## 3. SKILL.md 格式

`SKILL.md` 必须以 YAML frontmatter 开头：

```markdown
---
name: <skill-name>
description: <一句话说明：做什么 + 什么时候用>
---

# 标题

## When to use / 适用场景
...

## Instructions / 操作步骤
...
```

### 3.1 必填字段

- `name`
- `description`

`description` 要求：

- 非空
- 1-1024 字符
- 建议包含任务关键词（帮助模型匹配），同时说明使用时机

### 3.2 可选字段（本项目会忽略，但建议保留以兼容生态）

- `license`
- `compatibility`
- `metadata`（map）
- `allowed-tools`（实验性字段，不同实现支持不一）

## 4. 指令正文编写建议

建议 SKILL.md 正文包含以下内容（越结构化越稳定）：

- **目标**：技能要产出什么
- **输入**：用户会给什么
- **输出**：明确输出格式（如要求严格 JSON）
- **步骤**：按序列出可执行的步骤
- **边界条件**：常见失败/不确定时如何处理
- **示例**：1-2 个小样例（输入与期望输出）

如果你要求模型“只输出 JSON”，请在正文中多次强调：

- 只输出 JSON
- 不要 Markdown
- 不要解释性文字

## 5. 资源文件读取规范（重要）

本项目提供工具 `read_skill_file(skill_name, filename)` 供模型读取 skill 的附加资料。

出于安全原因，当前实现**只允许读取**：

- `references/<...>`
- `assets/<...>`

也就是说：

- `filename` 必须形如 `references/xxx.md` 或 `assets/schema.json`
- 不允许绝对路径
- 不允许包含 `..`

### 5.1 在 SKILL.md 中引用资源

推荐在 SKILL.md 中用明确相对路径描述，例如：

- `请先阅读 references/REFERENCE.md`
- `输出必须满足 assets/event_schema.json`

（是否采用 `[[...]]` 语法由你自行约定；本项目不强制解析该语法，模型可自行决定是否调用 `read_skill_file`。）

## 6. 脚本执行规范

本项目提供工具 `execute_skill_script(skill_name, script_name, args="")`。

建议将脚本放在：

- `scripts/` 目录下

例如：

- `scripts/extract.py`

注意事项：

- 当前实现支持：`.py` 与 `.sh`
- Windows 环境通常缺省没有 `bash`，`.sh` 可能无法运行
- 建议脚本：
  - 自包含、错误信息清晰
  - 对输入参数做校验
  - 控制执行时间（脚本侧也应避免长时间运行）

## 7. 编写检查清单

提交一个新 skill 前，建议自检：

- 目录名与 `name` 一致
- `description` 清晰，包含使用时机关键词
- 输出格式（尤其 JSON）描述明确
- 引用文件都放在 `references/` 或 `assets/`
- 如包含脚本，脚本放在 `scripts/` 且能在本机运行

## 8. SKILL.md 模板（可复制）

```markdown
---
name: my-skill
description: 用一句话描述这个技能做什么，以及什么时候使用（包含关键词）。
---

# My Skill

## 目标

- 说明你要解决的问题。

## 输入

- 用户将提供：...

## 输出（必须严格只输出 JSON）

输出一个 JSON object：

- `field_a`: string
- `field_b`: array

约束：

1. 只输出 JSON，不要 Markdown，不要解释文字。
2. 若不确定，输出字段但用 `null` 或空数组占位。

## 适用场景

- 场景 1
- 场景 2

## 操作步骤

1. 第一步做什么
2. 如需参考资料，调用 `read_skill_file(my-skill, "references/REFERENCE.md")`
3. 如需执行脚本，调用 `execute_skill_script(my-skill, "scripts/run.py", "<args>")`

## 示例

输入：
...

输出：
{ "field_a": "...", "field_b": [] }
```
