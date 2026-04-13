"""grag.preprocessing.document_processor

文档处理模块（Document Processor）

职责：
- 支持多种文档格式的读取和处理
- 支持的格式：txt, docx, doc, pdf, csv, xlsx, 图片
- 使用视觉模型进行图像OCR
- 将各种格式统一转换为标准文本

说明：
- 图片格式使用视觉模型进行OCR识别
- 文档处理后通过LLM整理成标准格式
- 支持批量处理
"""

import os
from pathlib import Path
from typing import Optional, Union, List, Dict, Any
import logging
import re

# 文档处理库
try:
    import docx
except ImportError:
    docx = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from PIL import Image
except ImportError:
    Image = None

from ..model import get_vision_client
from ..config import get_config_manager
from .text_cleaner import TextCleaner


logger = logging.getLogger(__name__)


class DocumentProcessor:
    """文档处理器
    
    支持多种文档格式的读取和处理
    """
    
    # 支持的文件格式
    SUPPORTED_TEXT_FORMATS = {'.txt', '.md'}
    SUPPORTED_DOC_FORMATS = {'.docx', '.doc'}
    SUPPORTED_PDF_FORMATS = {'.pdf'}
    SUPPORTED_TABLE_FORMATS = {'.csv', '.xlsx', '.xls'}
    SUPPORTED_IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    
    def __init__(
        self,
        vision_provider: Optional[str] = None,
        llm_provider: Optional[str] = None
    ):
        """初始化文档处理器
        
        Args:
            vision_provider: 视觉模型提供商名称
            llm_provider: LLM提供商名称
        """
        self.vision_provider = vision_provider
        self.llm_provider = llm_provider
        self._vision_client = None
        # 文本清洗 / 标准化由 TextCleaner 负责
        self._text_cleaner: Optional[TextCleaner] = None
        self._settings = get_config_manager().get_settings()
        self._doc_processing_cfg = dict(getattr(self._settings.preprocessing, 'document_processing', {}) or {})
        self._supported_formats = self._resolve_supported_formats()
        self._max_file_size_bytes = self._parse_size_to_bytes(self._doc_processing_cfg.get('max_file_size'))
        self._preferred_encoding = str(self._doc_processing_cfg.get('encoding', 'utf-8') or 'utf-8').strip() or 'utf-8'
        
    def _get_vision_client(self):
        """获取视觉模型客户端（懒加载）"""
        if self._vision_client is None:
            self._vision_client = get_vision_client(self.vision_provider)
        return self._vision_client
    
    def _get_llm_client(self):
        """兼容旧接口：返回 TextCleaner 使用的 LLM 客户端。

        说明：
        - 推荐直接通过 TextCleaner 执行标准化；此方法仅供测试和向后兼容使用。
        """
        if self._text_cleaner is None:
            self._text_cleaner = TextCleaner(self.llm_provider)
        return self._text_cleaner._get_llm_client()
    
    def process_file(
        self,
        file_path: Union[str, Path],
        standardize: bool = True
    ) -> str:
        """处理单个文件
        
        Args:
            file_path: 文件路径
            standardize: 是否使用LLM标准化文档格式
            
        Returns:
            处理后的文本内容
            
        Raises:
            ValueError: 不支持的文件格式
            FileNotFoundError: 文件不存在
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if self._max_file_size_bytes is not None and file_path.stat().st_size > self._max_file_size_bytes:
            raise ValueError(f"文件超过大小限制: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix not in self._supported_formats:
            raise ValueError(f"文件格式未在配置允许列表中: {suffix}")
        
        # 根据文件类型选择处理方法
        if suffix in self.SUPPORTED_TEXT_FORMATS:
            content = self._process_text_file(file_path)
        elif suffix in self.SUPPORTED_DOC_FORMATS:
            content = self._process_doc_file(file_path)
        elif suffix in self.SUPPORTED_PDF_FORMATS:
            content = self._process_pdf_file(file_path)
        elif suffix in self.SUPPORTED_TABLE_FORMATS:
            content = self._process_table_file(file_path)
        elif suffix in self.SUPPORTED_IMAGE_FORMATS:
            content = self._process_image_file(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")
        
        # 使用LLM标准化文档
        if standardize and content:
            content = self._standardize_document(content, file_path.name)
        
        return content
    
    def _process_text_file(self, file_path: Path) -> str:
        """处理文本文件"""
        try:
            with open(file_path, 'r', encoding=self._preferred_encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            for encoding in [self._preferred_encoding, 'utf-8', 'gbk', 'gb2312', 'latin-1']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            raise ValueError(f"无法解码文件: {file_path}")
    
    def _process_doc_file(self, file_path: Path) -> str:
        """处理Word文档"""
        if docx is None:
            raise ImportError("处理Word文档需要安装: pip install python-docx")
        
        try:
            doc = docx.Document(file_path)
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            
            # 处理表格
            tables_text = []
            for table in doc.tables:
                table_data = []
                for row in table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    table_data.append(' | '.join(row_data))
                if table_data:
                    tables_text.append('\n'.join(table_data))
            
            content = '\n\n'.join(paragraphs)
            if tables_text:
                content += '\n\n' + '\n\n'.join(tables_text)
            
            return content
        except Exception as e:
            logger.error(f"处理Word文档失败 {file_path}: {e}")
            raise
    
    def _process_pdf_file(self, file_path: Path) -> str:
        """处理PDF文件"""
        if PdfReader is None:
            try:
                import PyPDF2  # type: ignore
            except ImportError:
                PyPDF2 = None  # type: ignore

            if PyPDF2 is None:
                raise ImportError("处理PDF需要安装: pip install pypdf")
        
        try:
            with open(file_path, 'rb') as f:
                if PdfReader is not None:
                    pdf_reader = PdfReader(f)
                else:
                    pdf_reader = PyPDF2.PdfReader(f)  # type: ignore[attr-defined]
                text_parts = []
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    if text.strip():
                        text_parts.append(f"--- 第 {page_num + 1} 页 ---\n{text}")
                
                return '\n\n'.join(text_parts)
        except Exception as e:
            logger.error(f"处理PDF失败 {file_path}: {e}")
            raise
    
    def _process_table_file(self, file_path: Path) -> str:
        """处理表格文件（CSV, Excel）"""
        if pd is None:
            raise ImportError("处理表格文件需要安装: pip install pandas openpyxl")
        
        try:
            suffix = file_path.suffix.lower()
            
            if suffix == '.csv':
                # 尝试不同的编码
                for encoding in ['utf-8', 'gbk', 'gb2312']:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    df = pd.read_csv(file_path)
            else:  # xlsx, xls
                df = pd.read_excel(file_path)
            
            # 转换为文本格式
            return df.to_string(index=False)
        except Exception as e:
            logger.error(f"处理表格文件失败 {file_path}: {e}")
            raise
    
    def _process_image_file(self, file_path: Path) -> str:
        """处理图像文件（使用OCR）"""
        try:
            vision_client = self._get_vision_client()
            content = vision_client.ocr_image(file_path)
            return content
        except Exception as e:
            logger.error(f"OCR处理失败 {file_path}: {e}")
            raise
    
    def _standardize_document(self, content: str, filename: str) -> str:
        """使用 TextCleaner + LLM 标准化文档格式。

        说明：
        - 文本解析（PDF/Word/CSV/OCR 等）在本类中完成；
        - 语义级的“格式整理/纠错”等交给 TextCleaner 里的大模型处理。
        """
        try:
            if self._text_cleaner is None:
                self._text_cleaner = TextCleaner(self.llm_provider)
            # 先做基础清洗，再做大模型标准化
            cleaned = self._text_cleaner.basic_clean(content)
            return self._text_cleaner.standardize_with_llm(cleaned, filename)
        except Exception as e:
            logger.warning(f"文档标准化失败，返回原始内容: {e}")
            return content
    
    def batch_process(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        standardize: bool = True,
        recursive: bool = False
    ) -> Dict[str, Any]:
        """批量处理文档
        
        Args:
            input_dir: 输入目录
            output_dir: 输出目录
            standardize: 是否标准化文档
            recursive: 是否递归处理子目录
            
        Returns:
            处理结果统计
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'errors': []
        }
        
        # 获取所有支持的文件
        all_formats = self._supported_formats
        
        pattern = '**/*' if recursive else '*'
        files = []
        for fmt in all_formats:
            files.extend(input_dir.glob(f'{pattern}{fmt}'))
        
        results['total'] = len(files)
        
        for file_path in files:
            try:
                logger.info(f"处理文件: {file_path}")
                
                # 处理文件
                content = self.process_file(file_path, standardize=standardize)
                
                # 保存结果
                relative_path = file_path.relative_to(input_dir)
                output_file = output_dir / relative_path.with_suffix('.txt')
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                results['success'] += 1
                logger.info(f"成功处理: {file_path} -> {output_file}")
                
            except Exception as e:
                results['failed'] += 1
                error_msg = f"{file_path}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(f"处理失败: {error_msg}")
        
        return results
    
    def get_supported_formats(self) -> List[str]:
        """获取支持的文件格式列表"""
        return sorted(list(self._supported_formats))

    @classmethod
    def _implemented_formats(cls) -> set[str]:
        return (
            cls.SUPPORTED_TEXT_FORMATS |
            cls.SUPPORTED_DOC_FORMATS |
            cls.SUPPORTED_PDF_FORMATS |
            cls.SUPPORTED_TABLE_FORMATS |
            cls.SUPPORTED_IMAGE_FORMATS
        )

    def _resolve_supported_formats(self) -> set[str]:
        configured = self._doc_processing_cfg.get('supported_formats')
        implemented = self._implemented_formats()
        if not isinstance(configured, list) or not configured:
            return implemented
        normalized = set()
        for item in configured:
            value = str(item or '').strip().lower()
            if not value:
                continue
            if not value.startswith('.'):
                value = f'.{value}'
            normalized.add(value)
        matched = normalized & implemented
        return matched or implemented

    @staticmethod
    def _parse_size_to_bytes(raw: Any) -> Optional[int]:
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            return None
        m = re.match(r'^(\d+(?:\.\d+)?)(B|KB|MB|GB)$', value.upper())
        if not m:
            return None
        amount = float(m.group(1))
        unit = m.group(2)
        factors = {'B': 1, 'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 * 1024 * 1024}
        return int(amount * factors[unit])


# 全局单例
_default_processor: Optional[DocumentProcessor] = None


def get_document_processor(
    vision_provider: Optional[str] = None,
    llm_provider: Optional[str] = None
) -> DocumentProcessor:
    """获取文档处理器实例
    
    Args:
        vision_provider: 视觉模型提供商
        llm_provider: LLM提供商
        
    Returns:
        DocumentProcessor实例
    """
    global _default_processor
    if _default_processor is None or vision_provider is not None or llm_provider is not None:
        _default_processor = DocumentProcessor(vision_provider, llm_provider)
    return _default_processor
