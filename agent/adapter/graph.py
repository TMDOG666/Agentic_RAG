"""adapter.graph
 
 接入层（Adapter Layer）：LangGraph 工作流
 
 本模块负责把“模型推理（Agent）”与“工具执行（Tools）”组织成一个可循环的工作流：
 
 - `agent` 节点：调用大模型（绑定 Tools），由模型决定是否需要调用工具
 - `tools` 节点：执行工具调用（加载 skill / 读文件 / 执行脚本）
 - 条件边：如果模型输出包含 tool calls，则转到 `tools`；否则结束
 
 该模块只关心“如何编排”，不关心每个工具的具体实现细节。
 """
 
import os
 
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


def create_system_prompt(skill_manager) -> str:
    """生成系统提示词（system prompt）。
 
     system prompt 会在每次模型调用时作为第一条 system message 注入，主要用于：
 
     - 设定全局规则（语言、输出风格、工具使用原则）
     - 告知可用工具及用途
     - 注入 Skills 列表（由 SkillManager 提供），便于模型按需加载技能指令
 
     Args:
         skill_manager: SkillManager 实例，用于提供技能列表提示。
 
     Returns:
         str: 系统提示词文本。
     """
    return (
        "你是一个有帮助的智能助手。\n\n"
        "重要规则：\n"
        "1. 优先直接回答用户的问题；如果问题依赖项目内文档/知识库，请先检索再回答。\n"
        "2. 工具调用必须使用 function calling 机制；严禁在输出文本中伪造 <tool_call>...</tool_call>。\n"
        "3. 始终用中文回复。\n"
        "4. 每次回复都必须包含实际内容。\n\n"
        "可用工具只有以下 3 个（不要编造其它工具名）：\n"
        "- load_skill(skill_name): 加载技能指令\n"
        "- read_skill_file(skill_name, filename): 读取技能目录中的额外文件\n"
        "- execute_skill_script(skill_name, script_name, args): 执行技能脚本\n\n"
        "当你需要使用 RAG 检索时：\n"
        "1) 先 load_skill('rag-retrieval') 阅读使用方式\n"
        "2) 再用 execute_skill_script 执行 rag-retrieval 的脚本（例如 chunks_vector.py / chunks_keyword.py 等）\n"
        "3) 拿到结果后再基于证据回答\n\n"
        f"{skill_manager.get_skills_prompt()}"
    )


def build_graph(*, model, tools, system_prompt: str):
    """构建并编译 LangGraph 工作流。
 
     工作流结构：
 
     1. START -> agent
     2. agent 根据 tools_condition 决定：
        - 需要工具：agent -> tools -> agent (循环)
        - 不需要工具：agent -> END
 
     Args:
         model: LangChain Chat 模型对象（需支持 `.bind_tools()` 和 `.invoke()`）。
         tools: 供模型调用的工具列表（LangChain Tools）。
         system_prompt: system message 内容。
 
     Returns:
         编译后的可执行图对象（具备 `.invoke()` 方法）。
     """
    def agent_node(state: MessagesState):
        """LangGraph 节点：调用模型并返回一条 AI 消息。
 
         该节点会将 `tools` 绑定到模型上，从而允许模型产生 tool_calls。
         LangGraph 会把节点返回的消息追加到 `state["messages"]`。
         """
        # 将工具绑定到模型：让模型能够以 function calling 的方式请求工具执行。
        bound_model = model.bind_tools(tools)

        try:
            # 注入 system prompt + 历史消息，让模型在同一上下文里决策。
            response = bound_model.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    *state["messages"],
                ]
            )

            if os.environ.get("DEBUG"):
                # 调试输出：帮助定位
                # - 模型返回类型/内容
                # - content 是否为空
                # - 是否包含 tool_calls
                print(f"\n[调试] 响应类型: {type(response)}")
                print(f"[调试] 响应内容: {response}")
                if hasattr(response, "content"):
                    print(f"[调试] content 属性: {response.content}")
                if hasattr(response, "tool_calls"):
                    print(f"[调试] tool_calls 属性: {response.tool_calls}")

            # 返回增量更新：把当前 response 作为一条新消息追加。
            return {"messages": [response]}

        except Exception as e:
            print(f"\n❌ agent_node 错误: {e}")
            import traceback

            traceback.print_exc()
            raise

    workflow = StateGraph(MessagesState)

    # agent: 模型推理节点
    workflow.add_node("agent", agent_node)
    # tools: 工具执行节点（LangGraph 内置 ToolNode）
    workflow.add_node("tools", ToolNode(tools))

    # 启动时先让模型尝试回答/决定是否需要工具。
    workflow.add_edge(START, "agent")

    # 条件边：检测模型输出是否包含 tool_calls。
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: END,
        },
    )

    # 工具执行完后回到 agent：让模型综合工具结果继续推理。
    workflow.add_edge("tools", "agent")

    return workflow.compile()
