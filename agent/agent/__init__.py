"""agent

Agent 层（Agent Layer）包。

该层定义“智能体对外运行接口”，例如：
- CLI 交互入口
- 单轮调用入口（供 app 层流水线复用）

Agent 层只依赖更底层的 adapter 层来完成 runtime 组装，不直接拼装 skills/tools/llm。
核心入口：`agent.agent_with_skills`。
"""
