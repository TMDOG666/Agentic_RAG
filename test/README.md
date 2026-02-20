# GraphRAG 测试套件（pytest）

本目录包含 GraphRAG 项目的所有测试代码。

## 目录结构

```
test/
├── README.md                    # 本文件
├── grag/                        # grag 包的测试
│   └── config/                  # config 模块测试
│       ├── README.md            # 配置测试说明
│       ├── test_config_loader.py
│       ├── test_config_manager.py
│       ├── test_settings.py
│       └── run_all_tests.py
└── __init__.py
```

## 快速开始

所有测试统一使用 `pytest` 运行。

从项目根目录执行：

```bash
pytest
```

如果你希望看到 `print(...)` 输出：

```bash
pytest -s
```

如果你希望更详细的用例名输出：

```bash
pytest -v
```

只跑某个目录：

```bash
pytest test/grag/graph_construction
pytest test/grag/storage
```

只跑某个文件：

```bash
pytest test/grag/graph_construction/test_graph_builder.py
```

只跑某个用例（按关键字筛选）：

```bash
pytest -k graph_builder
pytest -k real_connection
```

## 统一运行规范（不要用环境变量控制测试行为）

本仓库测试运行参数统一通过 `pytest` 命令行参数与 marker 控制。

### 集成测试（REAL 外部依赖）

对需要真实外部依赖（真实 LLM/Embedding + 真实 DB）的用例使用：

```bash
pytest -m integration -s
```

### 人工检查 DB：暂停与不清理

当你需要在测试结束后进入数据库（Postgres/Milvus/Neo4j）人工查看写入结果时：

- **暂停 N 秒后再清理**：

```bash
pytest -m integration -s --pause 600
```

- **完全不清理（保留数据）**：

```bash
pytest -m integration -s --no-cleanup
```

说明：
- 以上参数由 `test/conftest.py` 统一提供。
- 默认行为是：测试结束后会清理写入数据，避免污染真实库。

## 已实现的测试

### ✅ Config 模块测试

位置：`test/grag/config/`

测试覆盖：
- ConfigLoader - 配置文件加载和缓存
- Settings - 类型化配置对象
- ConfigManager - 配置管理器
- 数据库配置验证（Neo4j, Milvus, PostgreSQL）

运行：

```bash
pytest test/grag/config
```

### ✅ Graph Construction 测试

位置：`test/grag/graph_construction/`

运行：

```bash
pytest test/grag/graph_construction
```

说明：
- 端到端（不落库）用例会注入 fake LLM/fake embedding，避免请求外部大模型。
- real-db 用例会真实连接并写入 Postgres/Milvus/Neo4j，然后清理写入数据。

### ✅ Storage 测试（REAL DB）

位置：`test/grag/storage/`

运行：

```bash
pytest test/grag/storage
```

## 测试规范

### 测试文件命名

- 测试文件以 `test_` 开头
- 测试类以 `Test` 开头
- 测试方法以 `test_` 开头

### 测试结构

```python
class TestModuleName:
    """测试模块说明"""
    
    def setup_method(self):
        """每个测试前执行的设置"""
        pass
    
    def test_feature_name(self):
        """测试功能说明"""
        print("\n=== 测试功能名称 ===")
        
        # 测试代码
        result = some_function()
        
        # 断言
        assert result is not None, "结果不应为空"
        
        print(f"✅ 测试通过")
```

### 运行测试的方式

统一使用 `pytest`。

## 添加新测试

### 1. 创建测试文件

在相应的模块目录下创建 `test_<module_name>.py`：

```python
"""测试 <模块名称>"""

import sys
from pathlib import Path

from grag.module import function_to_test


class TestModuleName:
    """测试类说明"""
    
    def test_feature(self):
        """测试功能"""
        print("\n=== 测试功能 ===")
        
        result = function_to_test()
        assert result is not None
        
        print("✅ 测试通过")
```

### 2. 更新测试套件

无需更新任何“聚合脚本”。pytest 会自动收集 `test_*.py` 与其中 `test_*` 用例。

## 测试最佳实践

1. **每个测试应该独立**
   - 不依赖其他测试的执行顺序
   - 使用 `setup_method` 进行初始化

2. **清晰的断言消息**
   ```python
   assert result is not None, "结果不应为空"
   assert len(items) > 0, "列表应包含至少一个元素"
   ```

3. **有意义的打印输出**
   ```python
   print(f"✅ 配置加载成功，包含 {len(config)} 个键")
   print(f"   默认提供商: {config['provider']}")
   ```

4. **异常处理**
   ```python
   try:
       result = risky_operation()
   except SpecificException as e:
       print(f"❌ 预期的异常: {e}")
   ```

## 持续集成

测试可以集成到 CI/CD 流程中：

```yaml
# .github/workflows/test.yml 示例
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run tests
        run: |
          pytest
```

## 故障排查

### 导入错误

如果遇到 `ModuleNotFoundError`：
1. 确认从项目根目录运行测试
2. 检查 `sys.path` 设置
3. 确认包结构完整（所有 `__init__.py` 文件存在）

### 配置文件未找到

如果遇到 `FileNotFoundError`：
1. 确认 `config/grag_config.yaml` 存在
2. 确认从正确的目录运行测试

### 编码问题（Windows）

如果遇到 `UnicodeEncodeError`：
- 测试脚本已包含 UTF-8 编码设置
- 确保使用提供的测试脚本运行

## REAL DB 测试前置条件（Postgres/Milvus/Neo4j）

本仓库包含部分真实数据库测试（例如 `test/grag/storage`、`test/grag/graph_construction/test_graph_builder.py`）。

在运行这些测试前，请确保：

- **Postgres**：服务可连接，且 `grag_config.yaml` 指向正确 host/port/user/password/database
- **Milvus**：服务可连接，且 collection schema 与代码一致
- **Neo4j**：服务可连接，且账号/数据库配置正确

另外，真实 LLM/Embedding 用例需要外部服务鉴权（API Key）。建议通过环境变量或你本地的密钥管理方式提供（避免把密钥写进仓库文件）。

建议先运行连接性检测用例：

```bash
pytest -k test_connection -s
```

### Milvus `doc_time` schema 报错

如果你看到类似错误（旧 collection 缺少 `doc_time` 字段），说明 Milvus 里存在旧 collection：

- 需要 **drop + recreate**（Milvus 不支持在线加字段）

处理方式（选一种）：

- 直接在 Milvus 里 drop 对应 collection
- 或者用你项目提供的 Milvus client/配置 drop 后再重跑测试

drop 完后，测试/代码会在首次写入时自动创建带 `doc_time` 的新 collection。

## 未来计划

- [ ] 增加 CI 中的数据库集成测试编排（例如 docker compose）
- [ ] 添加 Retrieval 模块测试
- [ ] 添加集成测试
- [ ] 添加性能测试
- [ ] 添加代码覆盖率报告

## 贡献

添加新测试时，请：
1. 遵循现有的测试结构和命名规范
2. 添加清晰的文档字符串
3. 包含有意义的断言消息
4. 更新相关的 README 文档
