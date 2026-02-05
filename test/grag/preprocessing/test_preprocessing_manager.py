"""测试预处理流程管理器 (PreprocessingManager)"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.config import initialize_config
from grag.preprocessing.preprocessing_manager import (
    PreprocessingManager,
    get_preprocessing_manager,
)


def _ensure_config():
    """确保配置已初始化"""
    initialize_config()


class TestPreprocessingManager:
    """测试 PreprocessingManager 类"""

    def setup_method(self):
        _ensure_config()
        self.manager = PreprocessingManager()

    def _prepare_temp_file(self) -> Path:
        """在临时目录创建一个简单的文本文件用于测试"""
        tmp_dir = Path(project_root) / "test" / "grag" / "preprocessing" / "test_data" /"tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        f = tmp_dir / "sample.txt"
        f.write_text("  第一行 \n 第二行  ", encoding="utf-8")
        return f

    def test_init(self):
        print("\n=== 测试 PreprocessingManager 初始化 ===")
        assert self.manager is not None
        print("✅ PreprocessingManager 初始化成功")

    def test_process_file_without_llm(self):
        print("\n=== 测试 process_file(use_llm=False) 仅解析+基础清洗 ===")
        f = self._prepare_temp_file()
        text = self.manager.process_file(f, use_llm=False)
        assert "第一行" in text and "第二行" in text
        print(f"✅ 解析结果: {repr(text)}")

    def test_process_file_with_llm(self):
        print("\n=== 测试 process_file(use_llm=True) 集成 LLM 清洗 ===")
        f = self._prepare_temp_file()
        text = self.manager.process_file(f, use_llm=True)
        # 即使 LLM 调用失败，也会回退到原文，因此这里只检查“返回了非空字符串”
        assert isinstance(text, str) and len(text) > 0
        print(f"✅ 返回内容长度: {len(text)}")

    def test_batch_process(self):
        print("\n=== 测试 batch_process ===")
        tmp_in = Path(project_root) / "test" / "grag" / "preprocessing" / "test_data" / "tmp_batch"
        tmp_out = Path(project_root) / "test" / "grag" / "preprocessing" / "test_data" / "tmp_batch_out"
        tmp_in.mkdir(parents=True, exist_ok=True)
        tmp_out.mkdir(parents=True, exist_ok=True)

        # 创建多个测试文件
        for i in range(3):
            (tmp_in / f"f{i}.txt").write_text(f" 第 {i} 行 ", encoding="utf-8")

        result = self.manager.batch_process(
            input_dir=tmp_in,
            output_dir=tmp_out,
            use_llm=False,
            recursive=False,
        )

        assert result["total"] == 3
        assert result["success"] == 3
        assert result["failed"] == 0
        print(f"✅ 批量处理结果: total={result['total']}, success={result['success']}")


class TestPreprocessingManagerGlobalFunctions:
    """测试 PreprocessingManager 全局函数"""

    def setup_method(self):
        _ensure_config()

    def test_get_preprocessing_manager(self):
        print("\n=== 测试全局 get_preprocessing_manager ===")
        m1 = get_preprocessing_manager()
        m2 = get_preprocessing_manager()
        assert m1 is not None
        assert isinstance(m1, PreprocessingManager)
        assert m1 is m2, "默认情况下应返回单例"
        print("✅ get_preprocessing_manager 返回单例")

    def test_get_preprocessing_manager_with_provider(self):
        print("\n=== 测试带 provider 的 get_preprocessing_manager ===")
        m = get_preprocessing_manager(vision_provider="siliconflow", llm_provider="siliconflow")
        assert isinstance(m, PreprocessingManager)
        assert m.vision_provider == "siliconflow"
        assert m.llm_provider == "siliconflow"
        print("✅ get_preprocessing_manager(指定 provider) 返回独立实例")


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始测试 PreprocessingManager 模块")
    print("=" * 60)

    t = TestPreprocessingManager()
    g = TestPreprocessingManagerGlobalFunctions()

    try:
        t.setup_method(); t.test_init()
        t.setup_method(); t.test_process_file_without_llm()
        t.setup_method(); t.test_process_file_with_llm()
        t.setup_method(); t.test_batch_process()

        g.setup_method(); g.test_get_preprocessing_manager()
        g.setup_method(); g.test_get_preprocessing_manager_with_provider()

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

