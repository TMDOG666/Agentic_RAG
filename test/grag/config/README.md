# GraphRAG Config 模块测试

本目录包含 `grag.config` 模块的测试脚本，用于验证配置加载、管理和设置功能。

## 测试文件

- `test_config_loader.py` - 测试配置加载器 (ConfigLoader)
- `test_settings.py` - 测试设置管理 (Settings)
- `test_config_manager.py` - 测试配置管理器 (ConfigManager)
- `run_all_tests.py` - 运行所有测试的主脚本

## 运行测试

### 运行所有测试

```bash
# 在项目根目录下运行
python test/grag/config/run_all_tests.py
```

### 运行单个测试模块

```bash
# 测试 ConfigLoader
python test/grag/config/test_config_loader.py

# 测试 Settings
python test/grag/config/test_settings.py

# 测试 ConfigManager
python test/grag/config/test_config_manager.py
```

### 使用 pytest 运行

如果安装了 pytest：

```bash
# 运行所有测试
pytest test/grag/config/

# 运行单个文件
pytest test/grag/config/test_config_loader.py

# 显示详细输出
pytest test/grag/config/ -v

# 显示打印输出
pytest test/grag/config/ -s
```

## 测试覆盖

### ConfigLoader 测试

- ✅ 加载 YAML 配置文件
- ✅ 获取嵌套配置值
- ✅ 设置配置值
- ✅ 环境变量插值替换
- ✅ 配置缓存机制
- ✅ 缓存信息查询

### Settings 测试

- ✅ 从配置创建设置对象
- ✅ 设置对象属性验证
- ✅ LLM 提供商配置
- ✅ Embedding 提供商配置
- ✅ 向量数据库配置 (Milvus)
- ✅ 图数据库配置 (Neo4j)
- ✅ 关系数据库配置 (PostgreSQL)
- ✅ 系统配置
- ✅ 预处理配置
- ✅ 图构建配置
- ✅ 检索配置

### ConfigManager 测试

- ✅ 配置管理器初始化
- ✅ 获取配置字典
- ✅ 获取设置对象
- ✅ 获取/设置配置值
- ✅ 获取提供商配置
- ✅ 配置验证结果
- ✅ 配置信息查询
- ✅ 数据库配置验证

## 测试要求

### 前置条件

1. 配置文件存在：`config/grag_config.yaml`
2. Python 环境已安装必要依赖：
   ```bash
   pip install pyyaml pydantic
   ```

### 可选依赖

- `pytest` - 用于更好的测试运行体验
- `pytest-cov` - 用于代码覆盖率报告

```bash
pip install pytest pytest-cov
```

## 测试输出示例

```
======================================================================
                    GraphRAG Config 模块测试套件
======================================================================

======================================================================
【1/3】测试 ConfigLoader 模块
======================================================================

=== 测试加载 grag_config.yaml ===
✅ 配置加载成功，包含 16 个顶层键
   默认 LLM 提供商: siliconflow
   默认向量数据库: milvus
   默认图数据库: neo4j

=== 测试获取嵌套配置值 ===
✅ LLM 模型: Qwen/Qwen3-Next-80B-A3B-Instruct
✅ Milvus 主机: localhost
✅ 不存在的键返回默认值: default_value

...

======================================================================
                            测试总结
======================================================================

总测试模块数: 3
✅ 通过: 3
❌ 失败: 0

======================================================================
🎉 所有测试通过！配置模块工作正常。
======================================================================
```

## 故障排查

### 配置文件未找到

如果出现 `FileNotFoundError: 配置文件不存在`：

1. 确认 `config/grag_config.yaml` 文件存在
2. 确认从项目根目录运行测试

### 导入错误

如果出现 `ModuleNotFoundError`：

1. 确认从项目根目录运行测试
2. 检查 Python 路径设置
3. 确认 `grag` 包结构完整

### 验证错误

如果出现 Pydantic 验证错误：

1. 检查配置文件格式是否正确
2. 确认所有必需字段都已填写
3. 检查数据类型是否匹配

## 扩展测试

如果需要添加新的测试：

1. 在相应的测试文件中添加测试方法
2. 方法名以 `test_` 开头
3. 使用 `assert` 进行断言
4. 添加清晰的打印输出

示例：

```python
def test_new_feature(self):
    """测试新功能"""
    print("\n=== 测试新功能 ===")
    
    # 测试代码
    result = some_function()
    
    # 断言
    assert result is not None, "结果不应为空"
    
    print(f"✅ 测试通过: {result}")
```
