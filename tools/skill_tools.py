"""tools.skill_tools
 
 Tool 层（Tool Layer）。
 
 该模块将 `SkillManager` 的能力封装为 LangChain Tools，以便大模型通过 function calling：
 
 - 按需加载某个 skill 的完整指令（`load_skill`）
 - 读取 skill 目录中的额外文件（`read_skill_file`）
 - 执行 skill 目录中的脚本（`execute_skill_script`）
 
 说明：
 - Tools 是“被动能力”，是否调用由模型在 LangGraph 工作流中决定。
 - 该模块只做参数适配与日志打印，不负责技能的业务实现。
 """
 
from langchain_core.tools import tool


def create_tools(skill_manager):
    """基于 SkillManager 创建可供模型调用的工具列表。
 
    Args:
        skill_manager: SkillManager 实例。
 
    Returns:
        list: LangChain Tool 列表。
    """
    @tool
    def load_skill(skill_name: str) -> str:
        """
        加载指定技能的完整指令

        当你判断用户的请求与某个技能相关时，使用此工具加载该技能的详细说明。

        参数:
            skill_name: 技能名称（例如 'data-analysis'）

        返回:
            技能的完整 SKILL.md 内容
        """
        print(f"🔧 [工具调用] 加载技能: {skill_name}")
        return skill_manager.load_skill(skill_name)

    @tool
    def read_skill_file(skill_name: str, filename: str) -> str:
        """
        读取技能目录中的额外文件

        当 SKILL.md 中引用了其他文件（例如 [[reference.md]]）时，使用此工具读取。

        参数:
            skill_name: 技能名称
            filename: 文件名（例如 'reference.md'）

        返回:
            文件内容
        """
        print(f"🔧 [工具调用] 读取技能文件: {skill_name}/{filename}")
        return skill_manager.read_skill_file(skill_name, filename)

    @tool
    def execute_skill_script(
        skill_name: str,
        script_name: str,
        args: str = "",
        script_args: str = "",
        **kwargs,
    ) -> str:
        """
        执行技能目录中的脚本

        某些技能提供了可执行脚本来完成特定任务。使用此工具执行这些脚本。

        参数:
            skill_name: 技能名称
            script_name: 脚本文件名（例如 'analyze.py'）
            script_args: 传递给脚本的参数（可选）

        返回:
            脚本的执行结果
        """
        # 说明：不同模型/中间层在传参时可能产生不同字段名。
        # - `args` / `script_args`：项目内部约定字段
        # - `v__args`：历史/兼容形态（避免 Pydantic/Tool schema 保留字冲突带来的变体）
        v_args = kwargs.get("v__args", "")
        effective_args = args or script_args or v_args
        print(f"🔧 [工具调用] 执行脚本: {skill_name}/{script_name} {effective_args}")
        return skill_manager.execute_skill_script(skill_name, script_name, effective_args)

    return [load_skill, read_skill_file, execute_skill_script]
