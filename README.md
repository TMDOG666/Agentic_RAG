# GraphRAG 智能体 Demo（AgentSkills 流程控制）

本项目目标：搭建一个**基于 GraphRAG 的 AI 智能体**，并使用 **AgentSkills** 实现“大模型流程控制/能力插件”机制（智能体基础）。

当前阶段重点在于：先把智能体运行时（LangGraph + Tools + Skills）跑通，并提供一个可复用的多技能编排示例；GraphRAG 知识侧能力将逐步补齐。

## ✅ 已实现

1. **AgentSkills 三层渐进式加载机制**
   - Level 1: 启动时加载所有 Skills 的元数据（name + description）
   - Level 2: 按需加载完整的 `SKILL.md` 内容
   - Level 3: 按需加载 Skills 引用的额外文件

2. **基于 LangGraph 的 Agent-Tools 循环**
   - 大模型根据系统提示词中的技能描述，自主决策是否调用技能
   - 通过工具调用加载 Skill 指令、读取 Skill 资源、执行脚本

3. **可执行脚本支持**
   - Skills 可以包含 Python/Bash 脚本
   - Agent 可以执行这些脚本完成确定性任务

4. **多技能编排示例（应用层流水线）**
   - `app/event_extraction_pipeline.py`: 多 Skill 串联（预处理/分句/逐句抽取/聚合）

5. **多 Provider 配置**
   - `agent_config.yaml` 支持切换不同 OpenAI Compatible / vLLM / Ollama 等后端

## 🚧 未完成（Roadmap）

- 集成多模态大模型实现语音图片视频的集成
- 集成向量数据库以及图数据库
- 实现实体关系抽取构建图关系
- 实现知识库的检索机制

## 📁 项目结构

```
.
├── agent_with_skills.py              # 智能体入口（LangGraph + Tools + Skills）
├── agent_config.yaml                 # 模型/Provider 配置
├── run_event_extraction_pipeline.py  # 事件抽取流水线运行入口
├── app/                              # 应用层：多技能编排示例
├── adapter/                          # 运行时组装（model/graph/skills/tools）
├── llm/                              # LLM 适配与配置
├── tools/                            # Agent 可调用工具（Skill 工具等）
├── skill/                            # SkillManager 权威逻辑
├── test_data.csv                     # 测试数据
├── README.md                         # 本文件
└── .cursor/skills/                   # Skills 目录
    ├── greeting-skill/               # 问候技能
    │   ├── SKILL.md
    │   ├── formal-greetings.md
    │   └── holiday-greetings.md
    ├── data-analysis/                # 数据分析技能
    │   ├── SKILL.md
    │   ├── analyze.py                # 可执行脚本
    │   └── advanced-analysis.md
    └── code-review/                  # 代码审查技能
        ├── SKILL.md
        └── python-review.md
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 切换到 langchain 环境
conda activate langchain

# 安装依赖（如果还没安装）
pip install langchain langchain-openai langchain-chroma langgraph pyyaml pandas openpyxl
```

### 2. 配置 API Key

```bash
# Windows CMD
set SILICONFLOW_API_KEY=your_api_key_here

# Windows PowerShell
$env:SILICONFLOW_API_KEY="your_api_key_here"

# Linux/Mac
export SILICONFLOW_API_KEY=your_api_key_here
```

### 3. 运行程序

```bash
python agent_with_skills.py
```

### 4. （可选）切换模型 Provider

编辑 `agent_config.yaml`：

- `provider`: 选择 `providers` 下的一个键（例如 `vllm` / `siliconflow` / `ollama`）
- `api_key_env`: 对应的环境变量名（例如 `SILICONFLOW_API_KEY` / `OPENAI_API_KEY`）

## 💡 使用示例

### 示例 1：测试问候技能

```
👤 你: 用正式的方式用中文问候我

🤖 助手: [会自动加载 greeting-skill 并使用正式问候语]
```

### 示例 2：测试数据分析技能

```
👤 你: 帮我分析一下 test_data.csv

🤖 助手: [会自动加载 data-analysis skill 并执行 analyze.py 脚本]
```

### 示例 3：测试代码审查技能

```
👤 你: 帮我审查这段 Python 代码：
def add(a, b):
    return a + b

🤖 助手: [会自动加载 code-review skill 并按照审查清单检查代码]
```

### 示例 4：查看可用技能

```
👤 你: skills

📚 可用技能：
  • greeting-skill: 当用户需要问候、打招呼或需要礼貌用语时使用此技能
  • data-analysis: 当用户需要分析数据、生成统计报告或处理 CSV/Excel 文件时使用此技能
  • code-review: 当用户需要审查代码、检查代码质量、发现潜在问题时使用此技能
```

## 🎓 工作原理

### 1. 启动阶段
```python
# SkillManager 扫描 .cursor/skills/ 目录
skill_manager = SkillManager()

# 提取所有 SKILL.md 的 YAML Frontmatter
# 生成包含所有 Skills 描述的系统提示词
SYSTEM_PROMPT = f"""
你可以使用以下技能：
- greeting-skill: 问候和礼貌用语
- data-analysis: 数据分析和统计
- code-review: 代码审查和优化建议
...
"""
```

### 2. 用户请求阶段
```python
# 用户: "帮我分析 test_data.csv"

# 大模型推理：
# 1. 看到系统提示词中有 data-analysis skill
# 2. 判断用户请求与该 skill 的描述匹配
# 3. 决定调用 load_skill 工具

# 大模型输出：
{
    "tool": "load_skill",
    "arguments": {"skill_name": "data-analysis"}
}
```

### 3. Skill 加载阶段
```python
# SkillManager 读取 .cursor/skills/data-analysis/SKILL.md
# 返回完整内容给大模型

# 大模型读到：
"""
使用 execute_skill_script 执行 analyze.py 脚本
"""

# 大模型输出：
{
    "tool": "execute_skill_script",
    "arguments": {
        "skill_name": "data-analysis",
        "script_name": "analyze.py",
        "args": "test_data.csv"
    }
}
```

### 4. 执行阶段
```python
# SkillManager 执行脚本
result = subprocess.run(['python', 'analyze.py', 'test_data.csv'])

# 返回脚本输出给大模型
# 大模型解读结果并生成用户友好的回复
```

## 🛠️ 创建自定义 Skill

### 1. 创建 Skill 目录
```bash
mkdir -p .cursor/skills/my-skill
```

### 2. 创建 SKILL.md
```markdown
---
name: my-skill
description: 这个技能的简短描述（用于大模型判断是否使用）
---

# 我的技能

## 概述
详细说明这个技能的用途

## 使用场景
- 场景 1
- 场景 2

## 指令
1. 步骤 1
2. 步骤 2
3. 如需更多信息，参考 [[details.md]]

## 可用脚本
- `script.py`: 脚本说明
```

### 3. 添加额外文件（可选）
```bash
# 创建引用的文档
echo "详细说明..." > .cursor/skills/my-skill/details.md

# 创建可执行脚本
echo "print('Hello from script')" > .cursor/skills/my-skill/script.py
```

### 4. 重启程序
```bash
python agent_with_skills.py
```

## 📊 技术栈

- **LangGraph**: 构建有状态的 Agent 工作流
- **LangChain**: 工具调用和模型集成
- **OpenAI Compatible / vLLM / Ollama**: 多种 LLM 后端（通过 `agent_config.yaml` 切换）
- **Chroma**: 向量数据库（用于 RAG，后续将与 GraphRAG/图数据库侧集成）
- **YAML**: 解析 Skill 元数据
- **Pandas**: 数据分析脚本

## 🔍 调试技巧

### 查看工具调用日志
程序会自动打印工具调用信息：
```
🔧 [工具调用] 加载技能: data-analysis
🔧 [工具调用] 执行脚本: data-analysis/analyze.py test_data.csv
```

### 检查 Skill 是否被识别
启动时会显示发现的 Skills：
```
✅ Skill Manager 初始化完成
📁 Skills 目录: C:\path\to\.cursor\skills
🎯 发现 3 个 Skills
   - greeting-skill
   - data-analysis
   - code-review
```

### 手动测试脚本
```bash
cd .cursor/skills/data-analysis
python analyze.py ../../test_data.csv
```

## 📚 参考资料

- [Agent Skills 官方网站](https://agentskills.io/)
- [Anthropic 博客文章](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 文档](https://python.langchain.com/)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
