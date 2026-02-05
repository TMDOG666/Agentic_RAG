"""agent_with_skills

兼容入口脚本（Compatibility Entrypoint）。

说明：
- 本仓库的权威 Agent 层实现位于：`agent.agent_with_skills`。
- 由于 README/历史使用习惯可能仍使用 `python agent_with_skills.py`，这里提供一个薄封装，
  将调用转发到 agent 层。

注意：
- 该文件不实现业务逻辑，也不组装 runtime；只是一个入口转发。
"""

from agent.agent_with_skills import main, run_once


__all__ = ["run_once", "main"]


if __name__ == "__main__":
    main()
