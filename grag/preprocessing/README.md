# 文档预处理模块

## 概述

文档预处理模块负责将各种格式的文档转换为标准化的文本格式，为后续的知识图谱构建提供统一的输入。

## 支持的文件格式

### 文本文件
- `.txt` - 纯文本文件
- `.md` - Markdown文件

### 文档文件
- `.docx` - Word文档（新格式）
- `.doc` - Word文档（旧格式）

### PDF文件
- `.pdf` - PDF文档

### 表格文件
- `.csv` - CSV表格
- `.xlsx` - Excel表格（新格式）
- `.xls` - Excel表格（旧格式）

### 图像文件（OCR）
- `.jpg` / `.jpeg` - JPEG图像
- `.png` - PNG图像
- `.gif` - GIF图像
- `.bmp` - BMP图像
- `.webp` - WebP图像

## 功能特性

### 1. 多格式支持
- 自动识别文件格式
- 统一的处理接口
- 支持批量处理

### 2. 图像OCR
- 使用视觉模型进行OCR识别
- 支持多种图像格式
- 高精度文字识别

### 3. 文档标准化
- 使用LLM整理文档格式
- 修正OCR错误
- 统一文档结构

### 4. 批量处理
- 支持目录批量处理
- 支持递归处理子目录
- 详细的处理结果统计

## 使用方法

### 基本使用

```python
from grag.preprocessing import get_document_processor

# 创建文档处理器
processor = get_document_processor()

# 处理单个文件
content = processor.process_file("document.pdf", standardize=True)

# 保存结果
with open("output.txt", "w", encoding="utf-8") as f:
    f.write(content)
```

### 批量处理

```python
from grag.preprocessing import get_document_processor

processor = get_document_processor()

# 批量处理目录中的所有文件
results = processor.batch_process(
    input_dir="grag/preprocessing/input",
    output_dir="grag/preprocessing/output",
    standardize=True,
    recursive=False
)

print(f"成功处理: {results['success']} 个文件")
print(f"失败: {results['failed']} 个文件")
```

### 指定模型提供商

```python
from grag.preprocessing import get_document_processor

# 使用特定的视觉模型和LLM
processor = get_document_processor(
    vision_provider="siliconflow",
    llm_provider="siliconflow"
)
```

## 配置说明

### 视觉模型配置

在 `config/grag_config.yaml` 中配置视觉模型：

```yaml
# 默认视觉模型提供商
vision_provider: siliconflow

# 视觉模型提供商配置
vision_providers:
  siliconflow:
    model: Qwen/Qwen3-VL-30B-A3B-Instruct
    base_url: https://api.siliconflow.cn/v1
    api_key_env: SILICONFLOW_API_KEY
    temperature: 0.1
    max_tokens: 4096
    timeout: 120
```

### 环境变量

设置API密钥环境变量：

```bash
# Windows
set SILICONFLOW_API_KEY=your_api_key

# Linux/Mac
export SILICONFLOW_API_KEY=your_api_key
```

## 目录结构

```
grag/preprocessing/
├── input/          # 输入文件目录（放置待处理的文档）
├── output/         # 输出文件目录（处理后的文本文件）
├── document_processor.py  # 文档处理器
├── text_cleaner.py        # 文本清洗
├── preprocessing_manager.py  # 预处理管理器
└── README.md       # 本文档
```

## 测试

运行测试脚本：

```bash
python test/grag/preprocessing/test_document_processor.py
```

测试步骤：
1. 将测试文件放入 `grag/preprocessing/input/` 目录
2. 运行测试脚本
3. 查看 `grag/preprocessing/output/` 目录中的处理结果

## 依赖安装

```bash
# 基础依赖
pip install openai

# Word文档支持
pip install python-docx

# PDF支持
pip install pypdf

# 表格支持
pip install pandas openpyxl

# 图像支持
pip install Pillow
```

## 注意事项

1. **API密钥**: 确保设置了正确的API密钥环境变量
2. **文件编码**: 文本文件会自动尝试多种编码（UTF-8, GBK, GB2312）
3. **图像质量**: 图像OCR效果取决于图像质量和视觉模型性能
4. **文档标准化**: 标准化过程会调用LLM，可能需要较长时间
5. **批量处理**: 大量文件处理时注意API调用限制

## 错误处理

- 不支持的文件格式会抛出 `ValueError`
- 文件不存在会抛出 `FileNotFoundError`
- 缺少依赖库会抛出 `ImportError` 并提示安装命令
- 处理失败的文件会记录在批量处理结果的 `errors` 列表中

## 性能优化建议

1. 对于大量文件，考虑分批处理
2. 图像文件建议先压缩以提高处理速度
3. 可以关闭 `standardize` 参数跳过LLM标准化步骤
4. 使用本地模型可以提高处理速度

## 后续扩展

- [ ] 支持更多文档格式（PPT、HTML等）
- [ ] 支持文档分块策略
- [ ] 支持元数据提取
- [ ] 支持并行处理
- [ ] 支持增量处理
