"""grag.config.config_manager

配置管理器（Configuration Manager）

职责：
- 统一管理所有配置相关操作
- 提供配置的初始化和验证流程
- 管理配置的生命周期
- 提供配置的运行时管理接口

说明：
- 作为配置层的统一入口
- 整合配置加载、验证、设置管理
- 提供便捷的配置访问方法
"""

import os
from typing import Any, Dict, Optional, List, Union
from pathlib import Path

from .config_loader import ConfigLoader, load_grag_config
from .config_validator import ConfigValidator, validate_grag_config, ValidationResult, ValidationLevel
from .settings import GraphRAGSettings, get_settings, create_settings_from_config, ProviderType


class ConfigManager:
    """配置管理器

    提供完整的配置管理功能，包括加载、验证、访问、更新等。
    """

    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        """初始化配置管理器

        Args:
            config_dir: 配置文件目录，默认自动查找
        """
        self.config_loader = ConfigLoader(config_dir)
        self.config_validator = ConfigValidator()
        self._settings: Optional[GraphRAGSettings] = None
        self._config: Optional[Dict[str, Any]] = None
        self._validation_results: List[ValidationResult] = []

    def initialize(self, config_name: str = "grag_config.yaml",
                  validate: bool = True) -> bool:
        """初始化配置管理器

        Args:
            config_name: 配置文件名
            validate: 是否执行验证

        Returns:
            初始化是否成功
        """
        try:
            # 加载配置
            self._config = self.config_loader.load_config(config_name)

            # 验证配置
            if validate:
                self._validation_results = self.config_validator.validate_config(self._config)
                if self.has_errors():
                    print("❌ 配置验证失败，存在错误:")
                    self.print_validation_summary()
                    return False

            # 创建设置对象
            self._settings = create_settings_from_config(self._config)

            if validate and self.has_warnings():
                print("⚠️  配置验证通过，但存在警告:")
                self.print_validation_summary()

            return True

        except Exception as e:
            print(f"配置初始化失败: {e}")
            return False

    def reload_config(self, config_name: str = "grag_config.yaml") -> bool:
        """重新加载配置

        Args:
            config_name: 配置文件名

        Returns:
            重新加载是否成功
        """
        # 清除缓存
        self.config_loader.clear_cache()

        # 重新初始化
        return self.initialize(config_name)

    def get_config(self) -> Dict[str, Any]:
        """获取原始配置字典

        Returns:
            配置字典

        Raises:
            RuntimeError: 配置未初始化
        """
        if self._config is None:
            raise RuntimeError("配置未初始化，请先调用 initialize()")
        return self._config.copy()

    def get_settings(self) -> GraphRAGSettings:
        """获取类型化的设置对象

        Returns:
            GraphRAGSettings对象

        Raises:
            RuntimeError: 配置未初始化
        """
        if self._settings is None:
            raise RuntimeError("配置未初始化，请先调用 initialize()")
        return self._settings

    def get_validation_results(self) -> List[ValidationResult]:
        """获取验证结果

        Returns:
            验证结果列表
        """
        return self._validation_results.copy()

    def has_errors(self) -> bool:
        """检查是否存在错误

        Returns:
            是否存在错误
        """
        return any(result.level == ValidationLevel.ERROR for result in self._validation_results)

    def has_warnings(self) -> bool:
        """检查是否存在警告

        Returns:
            是否存在警告
        """
        return any(result.level == ValidationLevel.WARNING for result in self._validation_results)

    def get_config_value(self, key_path: str, default: Any = None) -> Any:
        """获取配置值

        Args:
            key_path: 配置键路径，如 "llm_providers.siliconflow.model"
            default: 默认值

        Returns:
            配置值
        """
        return self.config_loader.get_config_value(self._config or {}, key_path, default)

    def set_config_value(self, key_path: str, value: Any) -> None:
        """设置配置值（仅修改内存中的配置）

        Args:
            key_path: 配置键路径
            value: 新值
        """
        if self._config is None:
            raise RuntimeError("配置未初始化")

        self.config_loader.set_config_value(self._config, key_path, value)

        # 重新创建设置对象
        try:
            self._settings = create_settings_from_config(self._config)
        except Exception as e:
            print(f"⚠️  配置更新后验证失败: {e}")

    def get_provider_config(self, provider_type: ProviderType,
                           provider_name: Optional[str] = None) -> Any:
        """获取指定类型的提供商配置

        Args:
            provider_type: 提供商类型
            provider_name: 提供商名称，使用默认提供商如果为None

        Returns:
            提供商配置对象

        Raises:
            RuntimeError: 配置未初始化
        """
        if self._settings is None:
            raise RuntimeError("配置未初始化")

        return self._settings.get_provider_config(provider_type, provider_name)

    def get_env_var(self, env_var_name: str, default: Optional[str] = None) -> Optional[str]:
        """获取环境变量值

        Args:
            env_var_name: 环境变量名
            default: 默认值

        Returns:
            环境变量值
        """
        return os.environ.get(env_var_name, default)

    def validate_current_config(self) -> List[ValidationResult]:
        """验证当前配置

        Returns:
            验证结果列表
        """
        if self._config is None:
            raise RuntimeError("配置未初始化")

        self._validation_results = self.config_validator.validate_config(self._config)
        return self._validation_results.copy()

    def print_validation_summary(self) -> None:
        """打印验证结果摘要"""
        if not self._validation_results:
            print("✅ 配置验证通过")
            return

        summary = self.config_validator.get_validation_summary(self._validation_results)

        print(f"\n📋 配置验证结果: {summary['total']} 个问题")
        print(f"❌ 错误: {summary['errors']} 个")
        print(f"⚠️  警告: {summary['warnings']} 个")
        print(f"ℹ️  信息: {summary['infos']} 个")

        if summary['error_messages']:
            print("\n❌ 错误详情:")
            for msg in summary['error_messages'][:5]:  # 只显示前5个
                print(f"  • {msg}")
            if len(summary['error_messages']) > 5:
                print(f"  ... 还有 {len(summary['error_messages']) - 5} 个错误")

        if summary['warning_messages']:
            print("\n⚠️  警告详情:")
            for msg in summary['warning_messages'][:5]:  # 只显示前5个
                print(f"  • {msg}")
            if len(summary['warning_messages']) > 5:
                print(f"  ... 还有 {len(summary['warning_messages']) - 5} 个警告")

    def export_config(self, file_path: Union[str, Path],
                     include_comments: bool = True) -> None:
        """导出当前配置到文件

        Args:
            file_path: 导出文件路径
            include_comments: 是否包含注释
        """
        import yaml

        if self._config is None:
            raise RuntimeError("配置未初始化")

        config_to_export = self._config.copy()

        # 可以在这里添加导出时的处理逻辑
        # 例如：移除敏感信息、添加导出时间戳等

        with open(file_path, 'w', encoding='utf-8') as f:
            if include_comments:
                f.write("# GraphRAG Configuration Export\n")
                f.write(f"# Generated at: {self.config_loader._get_current_time()}\n")
                f.write("# This is an exported configuration file\n\n")
            yaml.dump(config_to_export, f, default_flow_style=False, allow_unicode=True)

    def get_config_info(self) -> Dict[str, Any]:
        """获取配置信息摘要

        Returns:
            配置信息字典
        """
        info = {
            "initialized": self._settings is not None,
            "has_errors": self.has_errors(),
            "has_warnings": self.has_warnings(),
            "cache_info": self.config_loader.get_cache_info()
        }

        if self._settings:
            info.update({
                "llm_provider": self._settings.llm_provider,
                "embedding_provider": self._settings.embedding_provider,
                "reranker_provider": self._settings.reranker_provider,
                "vector_db_provider": self._settings.vector_db_provider,
                "graph_db_provider": self._settings.graph_db_provider,
                "relational_db_provider": self._settings.relational_db_provider,
            })

        return info

    def add_custom_validator(self, field_path: str, validator_func) -> None:
        """添加自定义验证器

        Args:
            field_path: 字段路径
            validator_func: 验证函数
        """
        self.config_validator.add_custom_validator(field_path, validator_func)


# 全局配置管理器实例
_config_manager_instance: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance


def initialize_config(config_name: str = "grag_config.yaml",
                     validate: bool = True) -> bool:
    """初始化全局配置

    Args:
        config_name: 配置文件名
        validate: 是否执行验证

    Returns:
        初始化是否成功
    """
    manager = get_config_manager()
    return manager.initialize(config_name, validate)


def get_grag_config() -> Dict[str, Any]:
    """获取GraphRAG配置字典

    Returns:
        配置字典

    Raises:
        RuntimeError: 配置未初始化
    """
    manager = get_config_manager()
    return manager.get_config()


def get_grag_settings() -> GraphRAGSettings:
    """获取GraphRAG设置对象

    Returns:
        GraphRAGSettings对象

    Raises:
        RuntimeError: 配置未初始化
    """
    manager = get_config_manager()
    return manager.get_settings()


def validate_config() -> List[ValidationResult]:
    """验证当前配置

    Returns:
        验证结果列表
    """
    manager = get_config_manager()
    return manager.validate_current_config()


def get_provider_config(provider_type: ProviderType, provider_name: Optional[str] = None) -> Any:
    """获取提供商配置

    Args:
        provider_type: 提供商类型
        provider_name: 提供商名称

    Returns:
        提供商配置对象
    """
    manager = get_config_manager()
    return manager.get_provider_config(provider_type, provider_name)