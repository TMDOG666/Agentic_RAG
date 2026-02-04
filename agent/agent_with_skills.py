"""agent.agent_with_skills
 
 Agent 层（Agent Layer）：对外运行入口
 
 职责：
 - 对外提供稳定的单轮调用接口：`run_once(user_text)`（供 app 层复用）
 - 提供一个本地 CLI 交互入口：`main()`
 
 非职责：
 - 不在本模块里拼装 skills/tools/llm（这些由 adapter 层 `create_runtime()` 统一完成）
 - 不在本模块里实现具体业务流程（业务编排属于 app 层）
 
 说明：
 - runtime 采用懒加载：首次调用 `run_once()` / `main()` 时才触发初始化，避免 import 触发重 I/O。
 
"""
import os
import time
from typing import Optional

from adapter.runtime import create_runtime

_RUNTIME = None


def _get_runtime() -> dict:
    """懒加载 runtime。
 
    说明：
    - `create_runtime()` 会触发 skills 扫描、模型初始化、graph 编译等较重的初始化。
    - 将其延迟到首次 `run_once()` / `main()` 调用时执行，避免“仅 import 模块就做大量工作”。
    """
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = create_runtime()
    return _RUNTIME


# ============================================================================
# 运行接口
# ============================================================================

def run_once(user_text: str) -> str:
    """
    执行一次对话
    
    Args:
        user_text: 用户输入
        
    Returns:
        Agent 的最终回复
    """
    # 允许通过环境变量调整重试策略，便于在不同 provider/网络环境下调参：
    # - API_RETRY_MAX: 最大重试次数
    # - API_RETRY_BASE_SLEEP: 基础等待时间（秒）
    max_retries = int(os.environ.get("API_RETRY_MAX", "5"))
    base_sleep = float(os.environ.get("API_RETRY_BASE_SLEEP", "2"))

    runtime = _get_runtime()
    graph = runtime["graph"]
 
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            # LangGraph 调用入口：传入一条 user message。
            # graph 内部会：
            # - 调用模型（可能触发 tool_calls）
            # - 执行工具（load/read/execute）
            # - 回到模型继续推理
            result = graph.invoke({"messages": [{"role": "user", "content": user_text}]})

            # 调试：打印完整的消息历史
            if os.environ.get("DEBUG"):
                print("\n[调试] 消息历史:")
                for msg in result["messages"]:
                    print(f"  {msg}")

            # 获取最后一条消息：通常是最终 AI 回复（也可能是 tool 结果之后的模型总结）。
            last_message = result["messages"][-1]

            # 兼容不同 message 类型：LangChain message 通常有 `.content` 属性。
            if hasattr(last_message, "content"):
                content = last_message.content
            else:
                content = str(last_message)

            # 空内容通常意味着：
            # - 认证失败导致 SDK 返回空
            # - provider 端异常
            # - 其它不可预期的返回
            if not content or content.strip() == "":
                return "❌ 模型返回了空内容，请检查 API Key 是否正确设置。"

            return content

        except Exception as e:
            last_error = e
            error_msg = str(e)
            print(f"\n❌ 错误详情: {error_msg}")

            lowered = error_msg.lower()
            is_rate_limited = (
                "rate" in lowered
                or "quota" in lowered
                or "tpm" in lowered
                or "429" in lowered
                or "rate limit" in lowered
            )

            # 429/TPM：指数退避重试（避免持续触发限流）。
            if is_rate_limited and attempt < max_retries - 1:
                sleep_s = base_sleep * (2**attempt)
                print(f"\n⏳ 检测到限流，{sleep_s:.1f}s 后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(sleep_s)
                continue

            # 其它错误：不重试，直接返回（避免陷入无意义循环）。
            if "api_key" in lowered or "authentication" in lowered:
                return "❌ API Key 错误，请检查 SILICONFLOW_API_KEY 环境变量是否正确设置。"
            elif "connection" in lowered or "timeout" in lowered:
                return "❌ 网络连接失败，请检查网络连接或 API 服务是否可用。"
            elif is_rate_limited:
                return "❌ API 调用超出限制，请稍后再试。"
            else:
                return f"❌ 发生错误: {error_msg}"

    return f"❌ 发生错误: {last_error}"


def main():
    """
    命令行交互界面
    """
    # CLI 交互入口：用于本地快速验证技能加载、工具调用与模型连通性。
    print("\n" + "="*60)
    print("🤖 Agent Skills 智能助手")
    print("="*60)
    print("💡 提示：输入 'exit' 或 'quit' 退出")
    print("💡 提示：输入 'skills' 查看可用技能")
    print("💡 提示：输入 'test' 测试 API 连接")
    print("💡 提示：输入 'debug' 开启调试模式")
    print("="*60)
    
    runtime = _get_runtime()
    skill_manager = runtime["skill_manager"]
    model = runtime["model"]
    agent_config = runtime["agent_config"]
 
    # provider 选择：优先环境变量覆盖，其次配置文件。
    provider = os.environ.get("AGENT_PROVIDER") or (agent_config.get("provider") if isinstance(agent_config, dict) else None) or "siliconflow"
    providers = (agent_config.get("providers") if isinstance(agent_config, dict) else None) or {}
    pconf = providers.get(provider) or {}
    # 用于提示用户“应该设置哪个环境变量作为 API Key”。
    api_key_env = pconf.get("api_key_env") or ("SILICONFLOW_API_KEY" if provider == "siliconflow" else "OPENAI_API_KEY")

    # base_url：本地/第三方服务的 OpenAI-Compatible 入口。
    base_url = os.environ.get("AGENT_BASE_URL") or pconf.get("base_url")
    if not base_url and provider == "siliconflow":
        base_url = os.environ.get("SILICONFLOW_BASE_URL")

    # api_key：允许用统一变量 AGENT_API_KEY 覆盖；否则使用 provider 指定的 api_key_env。
    api_key = os.environ.get("AGENT_API_KEY") or os.environ.get(api_key_env)
    if not api_key and provider == "siliconflow":
        api_key = os.environ.get("SILICONFLOW_API_KEY")

    # 对于本地网关（localhost/127.0.0.1），很多实现不校验 api_key，因此不强制提示。
    is_local = bool(base_url) and ("localhost" in str(base_url) or "127.0.0.1" in str(base_url))
    if not api_key and not is_local:
        print(f"\n⚠️  警告：未检测到 API Key 环境变量（provider={provider}, env={api_key_env}）")
        print("你可以设置：")
        print(f"- set {api_key_env}=your_key")
        print("或者使用 AGENT_API_KEY 覆盖\n")
    elif api_key:
        print(f"\n✅ API Key 已设置（前 10 位）: {api_key[:10]}...\n")
    
    # 调试模式标志：开启后会打印 LangGraph 返回的完整消息历史、模型响应对象结构等。
    debug_mode = False
    
    while True:
        try:
            user_text = input("👤 你: ").strip()
            
            if not user_text:
                continue
            
            if user_text.lower() in {"exit", "quit", "退出"}:
                print("\n👋 再见！")
                break
            
            if user_text.lower() == "debug":
                # debug 命令：通过环境变量控制 graph/agent 的调试输出。
                debug_mode = not debug_mode
                if debug_mode:
                    os.environ["DEBUG"] = "1"
                    print("\n🐛 调试模式已开启")
                else:
                    os.environ.pop("DEBUG", None)
                    print("\n🐛 调试模式已关闭")
                print()
                continue
            
            if user_text.lower() == "skills":
                # skills 命令：打印 SkillManager 扫描到的技能列表。
                print("\n📚 可用技能：")
                for name, info in skill_manager.skills_metadata.items():
                    print(f"  • {name}: {info['description']}")
                print()
                continue
            
            if user_text.lower() == "test":
                # test 命令：直接调用模型做一次最简单的连通性测试（绕过 graph/skills）。
                print("\n🧪 测试 API 连接...")
                try:
                    test_response = model.invoke([{"role": "user", "content": "你好"}])
                    if hasattr(test_response, 'content'):
                        print(f"✅ API 连接正常，模型回复: {test_response.content[:50]}...")
                    else:
                        print(f"✅ API 连接正常，收到响应: {str(test_response)[:50]}...")
                except Exception as e:
                    print(f"❌ API 连接失败: {e}")
                print()
                continue
            
            print()
            if debug_mode:
                print("🐛 [调试模式] 开始处理请求...\n")
            
            answer = run_once(user_text)
            print(f"🤖 助手: {answer}")
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}\n")


if __name__ == "__main__":
    main()
