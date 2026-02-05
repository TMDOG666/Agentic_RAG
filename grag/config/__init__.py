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
    load_grag_config,
    get_config_loader,
    get_config_value
)

from .config_validator import (
    ConfigValidator,
    validate_grag_config,
    ValidationResult,
    ValidationLevel,
    print_validation_results
)

from .settings import (
    GraphRAGSettings,
    ProviderType,
    get_settings,
    create_settings_from_config,
    reset_settings
)

from .config_manager import (
    ConfigManager,
    get_config_manager,
    initialize_config,
    get_grag_config,
    get_grag_settings,
    validate_config,
    get_provider_config
)

__all__ = [
    # 加载器
    "ConfigLoader",
    "load_grag_config",
    "get_config_loader",
    "get_config_value",

    # 验证器
    "ConfigValidator",
    "validate_grag_config",
    "ValidationResult",
    "ValidationLevel",
    "print_validation_results",

    # 设置
    "GraphRAGSettings",
    "ProviderType",
    "get_settings",
    "create_settings_from_config",
    "reset_settings",

    # 管理器
    "ConfigManager",
    "get_config_manager",
    "initialize_config",
    "get_grag_config",
    "get_grag_settings",
    "validate_config",
    "get_provider_config",
]