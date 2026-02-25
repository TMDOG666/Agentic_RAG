"""grag.config

配置层（Configuration Layer）

负责GraphRAG系统的配置管理，包括：
- 配置文件加载和解析
- 配置验证和类型检查
- 运行时配置管理
- 环境变量插值替换

主要组件：
- ConfigLoader: 配置文件加载器
- ConfigValidator: 配置验证器
- GraphRAGSettings: 类型化配置对象
- ConfigManager: 配置管理器
"""

from .config_loader import (
    ConfigLoader,
)

from .config_validator import (
    ConfigValidator,
    ValidationResult,
    ValidationLevel,
    print_validation_results
)

from .settings import (
    GraphRAGSettings,
    ProviderType,
    create_settings_from_config,
)

from .config_manager import (
    ConfigManager,
    get_config_manager,
)

__all__ = [
    # 加载器
    "ConfigLoader",

    # 验证器
    "ConfigValidator",
    "ValidationResult",
    "ValidationLevel",
    "print_validation_results",

    # 设置
    "GraphRAGSettings",
    "ProviderType",

    # 管理器
    "ConfigManager",
    "get_config_manager",
]