"""grag.preprocessing.preprocessing_manager

预处理流程管理器（Preprocessing Manager）

职责：
- 组织文档读取（DocumentProcessor）与文本清洗（TextCleaner）的整体流程
- 对上层（如 app/graph 构建流水线）提供统一的预处理入口

说明：
- DocumentProcessor 负责“按格式解析文件 -> 得到原始文本”
- TextCleaner 负责“文本级清洗 + 大模型标准化”
- 本管理器可以根据需要定制不同的预处理策略（例如只做解析，不做标准化等）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union, Dict, Any

from .document_processor import DocumentProcessor, get_document_processor
from .text_cleaner import TextCleaner


class PreprocessingManager:
    """预处理流程管理器"""

    def __init__(
        self,
        vision_provider: Optional[str] = None,
        llm_provider: Optional[str] = None,
    ):
        self.vision_provider = vision_provider
        self.llm_provider = llm_provider
        self._processor: Optional[DocumentProcessor] = None
        self._cleaner: Optional[TextCleaner] = None

    # ------------------------------------------------------------------
    # 内部组件获取
    # ------------------------------------------------------------------
    def _get_processor(self) -> DocumentProcessor:
        if self._processor is None:
            # 这里复用全局 get_document_processor，保证与其它模块行为一致
            self._processor = get_document_processor(
                vision_provider=self.vision_provider,
                llm_provider=self.llm_provider,
            )
        return self._processor

    def _get_cleaner(self) -> TextCleaner:
        if self._cleaner is None:
            self._cleaner = TextCleaner(self.llm_provider)
        return self._cleaner

    # ------------------------------------------------------------------
    # 对外预处理接口
    # ------------------------------------------------------------------
    def process_file(
        self,
        file_path: Union[str, Path],
        *,
        use_llm: bool = True,
    ) -> str:
        """预处理单个文件。

        Args:
            file_path: 文件路径
            use_llm: 是否使用大模型做标准化；False 时只做解析 + basic_clean
        """
        processor = self._get_processor()
        # DocumentProcessor 内部已经支持 standardize=True 的完整流程；
        # 这里额外提供一个“只做 basic_clean、不走 LLM”的分支。
        if use_llm:
            return processor.process_file(file_path, standardize=True)

        # 仅做解析 + basic_clean
        raw = processor.process_file(file_path, standardize=False)
        cleaner = self._get_cleaner()
        return cleaner.basic_clean(raw)

    def batch_process(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        *,
        use_llm: bool = True,
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """批量预处理文件。

        Args:
            input_dir: 输入目录
            output_dir: 输出目录
            use_llm: 是否使用大模型做标准化
            recursive: 是否递归处理子目录
        """
        processor = self._get_processor()
        return processor.batch_process(
            input_dir=input_dir,
            output_dir=output_dir,
            standardize=use_llm,
            recursive=recursive,
        )


_default_manager: Optional[PreprocessingManager] = None


def get_preprocessing_manager(
    vision_provider: Optional[str] = None,
    llm_provider: Optional[str] = None,
) -> PreprocessingManager:
    """获取预处理管理器单例"""
    global _default_manager
    if _default_manager is None and vision_provider is None and llm_provider is None:
        _default_manager = PreprocessingManager()
    elif vision_provider is not None or llm_provider is not None:
        # 显式指定 provider 时返回一个新的 manager，不污染默认单例
        return PreprocessingManager(vision_provider, llm_provider)
    return _default_manager or PreprocessingManager()
