"""测试文本清洗与标准化 (TextCleaner)"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.config import initialize_config, get_grag_settings, ProviderType
from grag.preprocessing.text_cleaner import TextCleaner


def _ensure_config():
    """确保配置已初始化"""
    initialize_config()


class TestTextCleaner:
    """测试 TextCleaner 类"""

    def setup_method(self):
        _ensure_config()
        self.cleaner = TextCleaner()

    def test_init(self):
        print("\n=== 测试 TextCleaner 初始化 ===")
        assert self.cleaner is not None
        print("✅ TextCleaner 初始化成功")

    def test_basic_clean(self):
        print("\n=== 测试 basic_clean 基础清洗 ===")
        raw = "  第一行  \r\n第二行 \n\n  第三行  "
        cleaned = self.cleaner.basic_clean(raw)
        # 统一换行 + 去首尾空白
        assert cleaned == "第一行\n第二行\n\n第三行"
        print(f"✅ basic_clean 结果: {repr(cleaned)}")

    def test_standardize_with_llm_fallback(self):
        """当 LLM 调用异常时应回退原文"""
        print("\n=== 测试 standardize_with_llm 降级回退 ===")

        # 构造一个会抛异常的假 LLM 客户端
        class FakeLLM:
            def chat(self, prompt: str) -> str:
                raise RuntimeError("fake error")

        self.cleaner._llm_client = FakeLLM()
        text = "这是正文"
        result = self.cleaner.standardize_with_llm(text, "test.txt")
        assert result == text, "LLM 失败时应回退到原始内容"
        print("✅ LLM 失败时正确回退到原文")

    def test_standardize_with_llm_success(self):
        """当 LLM 正常返回时应使用其结果"""
        print("\n=== 测试 standardize_with_llm 成功路径 ===")

        class FakeLLM:
            def __init__(self):
                self.called = False

            def chat(self, prompt: str) -> str:
                self.called = True
                # 简化：直接返回一个固定结果
                return "标准化后的内容"

        fake = FakeLLM()
        self.cleaner._llm_client = fake
        text = "原始内容"
        result = self.cleaner.standardize_with_llm(text, "demo.txt")
        assert fake.called is True, "应调用 LLM 的 chat 方法"
        assert result == "标准化后的内容"
        print("✅ standardize_with_llm 成功返回 LLM 结果")


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始测试 TextCleaner 模块")
    print("=" * 60)

    t = TestTextCleaner()

    try:
        t.setup_method(); t.test_init()
        t.setup_method(); t.test_basic_clean()
        t.setup_method(); t.test_standardize_with_llm_fallback()
        t.setup_method(); t.test_standardize_with_llm_success()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        raise


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)

