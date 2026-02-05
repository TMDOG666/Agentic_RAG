# 文档预处理测试

## 概述

本目录包含文档预处理模块的测试脚本。

## 测试内容

### 1. 文档处理器基本功能测试
- 配置初始化
- 文档处理器创建
- 支持格式检查
- 模型配置验证

### 2. 单文件处理测试
- 读取各种格式的文档
- OCR图像识别
- 文档标准化
- 结果保存

### 3. 批量处理测试
- 批量读取文件
- 递归处理子目录
- 处理结果统计
- 错误处理

## 运行测试

### 方法1：直接运行测试脚本

```bash
python test/grag/preprocessing/test_document_processor.py
```

### 方法2：使用运行脚本

```bash
python test/grag/preprocessing/run_tests.py
```

## 准备测试文件

1. 将测试文件放入输入目录：
   ```
   grag/preprocessing/input/
   ```

2. 支持的文件格式：
   - 文本：`.txt`, `.md`
   - 文档：`.docx`, `.doc`
   - PDF：`.pdf`
   - 表格：`.csv`, `.xlsx`, `.xls`
   - 图像：`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`

3. 运行测试后，结果将保存在：
   ```
   grag/preprocessing/output/
   ```

## 测试示例

### 示例1：测试文本文件

```bash
# 1. 创建测试文件
echo "这是一个测试文档" > grag/preprocessing/input/test.txt

# 2. 运行测试
python test/grag/preprocessing/test_document_processor.py

# 3. 查看结果
cat grag/preprocessing/output/test.txt
```

### 示例2：测试图像OCR

```bash
# 1. 将图像文件放入输入目录
cp your_image.jpg grag/preprocessing/input/

# 2. 运行测试
python test/grag/preprocessing/test_document_processor.py

# 3. 查看OCR结果
cat grag/preprocessing/output/your_image.txt
```

### 示例3：批量处理

```bash
# 1. 将多个文件放入输入目录
cp *.pdf grag/preprocessing/input/
cp *.docx grag/preprocessing/input/
cp *.jpg grag/preprocessing/input/

# 2. 运行批量处理测试
python test/grag/preprocessing/test_document_processor.py

# 3. 查看所有结果
ls grag/preprocessing/output/
```

## 环境要求

### 必需的环境变量

```bash
# 设置API密钥
export SILICONFLOW_API_KEY=your_api_key_here
```

### 必需的Python包

```bash
# 安装基础依赖
pip install openai

# 安装文档处理依赖
pip install python-docx PyPDF2 pandas openpyxl Pillow
```

## 测试输出说明

### 成功输出示例

```
======================================================================
GraphRAG 文档处理器测试套件
======================================================================

======================================================================
【1/3】测试 文档处理器基本功能
======================================================================

=== 初始化配置 ===
✅ 配置初始化成功

=== 创建文档处理器 ===
✅ 文档处理器创建成功

=== 支持的文件格式 ===
支持的格式: .bmp, .csv, .doc, .docx, .gif, .jpg, .jpeg, .md, .pdf, .png, .txt, .webp, .xls, .xlsx

=== 视觉模型配置 ===
提供商: siliconflow
模型: Qwen/Qwen3-VL-30B-A3B-Instruct
API地址: https://api.siliconflow.cn/v1

=== LLM配置 ===
提供商: siliconflow
模型: Qwen/Qwen3-Next-80B-A3B-Instruct
API地址: https://api.siliconflow.cn/v1

======================================================================
✅ 文档处理器测试通过
======================================================================
```

### 处理结果示例

```
--- 处理文件: sample.txt ---
✅ 成功处理，输出到: grag/preprocessing/output/sample.txt
   内容长度: 1234 字符
   预览: # GraphRAG 系统示例文档

## 简介

GraphRAG（Graph-based Retrieval Augmented Generation）是一个基于知识图谱的检索增强生成系统...
```

## 常见问题

### Q1: 测试失败，提示"配置未初始化"

**解决方案**：
1. 检查配置文件是否存在：`config/grag_config.yaml`
2. 确保配置文件格式正确
3. 检查是否添加了视觉模型配置

### Q2: 图像OCR失败

**解决方案**：
1. 检查API密钥是否正确设置
2. 确认网络连接正常
3. 检查图像文件是否损坏
4. 确认视觉模型配置正确

### Q3: 缺少依赖库

**解决方案**：
```bash
# 安装所有依赖
pip install python-docx PyPDF2 pandas openpyxl Pillow
```

### Q4: 文档标准化失败

**解决方案**：
1. 检查LLM API配置
2. 确认API密钥有效
3. 可以设置 `standardize=False` 跳过标准化

## 性能测试

### 测试不同文件格式的处理速度

```python
import time
from grag.preprocessing import get_document_processor

processor = get_document_processor()

# 测试处理时间
start = time.time()
content = processor.process_file("test.pdf", standardize=False)
elapsed = time.time() - start

print(f"处理时间: {elapsed:.2f} 秒")
print(f"内容长度: {len(content)} 字符")
```

## 调试技巧

### 启用详细日志

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 单独测试OCR

```python
from grag.model import get_vision_client

vision_client = get_vision_client()
result = vision_client.ocr_image("test.jpg")
print(result)
```

### 单独测试文档标准化

```python
from grag.model import get_llm_client

llm_client = get_llm_client()
response = llm_client.chat("请整理以下文档：\n\n" + raw_content)
print(response)
```

## 贡献指南

如果你想添加新的测试用例：

1. 在 `test_document_processor.py` 中添加新的测试函数
2. 函数名以 `test_` 开头
3. 在 `main()` 函数中注册新测试
4. 更新本README文档

## 相关文档

- [文档预处理模块README](../../../grag/preprocessing/README.md)
- [配置文件说明](../../../config/grag_config.yaml)
- [视觉模型客户端](../../../grag/model/vision_client.py)
- [文档处理器](../../../grag/preprocessing/document_processor.py)
