# GraphRAG 测试套件

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

### 从项目根目录运行所有测试

```bash
# 使用快捷脚本
python test_config.py
```

### 运行特定模块的测试

```bash
# 配置模块测试
python test/grag/config/run_all_tests.py

# 或单独运行某个测试文件
python test/grag/config/test_config_loader.py
```

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
python test/grag/config/run_all_tests.py
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

1. **直接运行 Python 脚本**
   ```bash
   python test/grag/config/test_config_loader.py
   ```

2. **使用 pytest**（如果已安装）
   ```bash
   pytest test/grag/config/
   pytest test/grag/config/ -v  # 详细输出
   pytest test/grag/config/ -s  # 显示 print 输出
   ```

3. **使用测试套件脚本**
   ```bash
   python test/grag/config/run_all_tests.py
   ```

## 添加新测试

### 1. 创建测试文件

在相应的模块目录下创建 `test_<module_name>.py`：

```python
"""测试 <模块名称>"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.module import function_to_test


class TestModuleName:
    """测试类说明"""
    
    def test_feature(self):
        """测试功能"""
        print("\n=== 测试功能 ===")
        
        result = function_to_test()
        assert result is not None
        
        print("✅ 测试通过")


def run_tests():
    """运行所有测试"""
    test = TestModuleName()
    test.test_feature()
    print("\n✅ 所有测试通过！")


if __name__ == "__main__":
    run_tests()
```

### 2. 更新测试套件

如果创建了新的测试模块，在 `run_all_tests.py` 中添加：

```python
# 测试新模块
try:
    from test_new_module import run_tests as run_new_tests
    run_new_tests()
    test_results["passed"] += 1
except Exception as e:
    test_results["failed"] += 1
    test_results["errors"].append(("NewModule", str(e)))
```

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
          python test_config.py
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

## 未来计划

- [ ] 添加 Model 模块测试
- [ ] 添加 Data 模块测试
- [ ] 添加 Graph Construction 模块测试
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
