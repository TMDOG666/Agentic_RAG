"""grag.preprocessing.text_cleaner

文本清洗与标准化模块（Text Cleaner）

职责：
- 执行通用的文本清洗（去空白、简单正则清理等）
- 调用 LLM 对文档内容做“语义层”的标准化清洗（格式整理、纠错等）

说明：
- 这里专注于“文本级”的处理，不关心文件格式（由 DocumentProcessor 负责）。
- 大模型相关的清洗统一收敛在本模块，便于后续替换/扩展策略。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..model import get_llm_client


logger = logging.getLogger(__name__)


class TextCleaner:
    """文本清洗与标准化器"""

    def __init__(self, llm_provider: Optional[str] = None):
        """初始化 TextCleaner

        Args:
            llm_provider: LLM 提供商名称，为 None 时使用配置中的默认值。
        """
        self.llm_provider = llm_provider
        self._llm_client = None

    # ------------------------------------------------------------------
    # 基础清洗（与大模型无关）
    # ------------------------------------------------------------------
    def basic_clean(self, text: str) -> str:
        """执行一些简单、与模型无关的文本清洗。

        当前实现较保守，只做：
        - 去掉首尾空白
        - 统一换行符
        后续可以按需增加：多余空行折叠、特殊字符清理等。
        """
        if not text:
            return text
        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 简单去掉行首尾空白
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # 大模型清洗（标准化）
    # ------------------------------------------------------------------
    def _get_llm_client(self):
        """懒加载 LLM 客户端"""
        if self._llm_client is None:
            self._llm_client = get_llm_client(self.llm_provider)
        return self._llm_client

    def standardize_with_llm(self, content: str, filename: str) -> str:
        """使用 LLM 对文档内容做标准化整理。

        Args:
            content: 原始文档内容（已完成格式层解析与基本清洗）
            filename: 文件名，用于提示模型了解文档类型/语境

        Returns:
            标准化后的文档内容；若模型调用失败，则回退为原始内容。
        """

        if not content:
            return content

        prompt = f"""请将以下文档内容整理成标准格式的文档。要求：

1. 保留所有重要信息和细节
2. 修正明显的OCR错误或格式问题
3. 统一格式，使用清晰的标题层级
4. 保持段落结构清晰
5. 如果有表格，保持表格格式
6. 不要添加原文中没有的内容
7. 直接输出整理后的文档，不要添加说明

文档名称: {filename}

原始内容:
{content}

请输出标准化后的文档："""

        try:
            llm_client = self._get_llm_client()
            return llm_client.chat(prompt)
        except Exception as e:
            # 由调用方决定是否接受“原始内容”作为降级结果
            logger.warning(f"文档标准化失败，返回原始内容: {e}")
            return content
