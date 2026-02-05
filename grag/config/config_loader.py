"""grag.config.config_loader

配置加载器（Configuration Loader）

职责：
- 加载YAML配置文件
- 处理环境变量替换
- 提供配置文件的热重载能力
- 验证配置文件的基本结构

说明：
- 支持从环境变量覆盖配置项
- 支持多配置文件合并
- 提供懒加载机制，避免每次都读取文件
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ConfigLoadResult:
    """配置加载结果"""
    config: Dict[str, Any]
    config_path: Path
    loaded_at: datetime
    checksum: str


class ConfigLoader:
    """配置文件加载器

    支持特性：
    - YAML配置文件加载
    - 环境变量插值替换
    - 配置缓存和热重载
    - 多配置文件合并
    """

    def __init__(self, config_dir: Union[str, Path] = None):
        """初始化配置加载器

        Args:
            config_dir: 配置文件目录，默认使用项目config目录
        """
        if config_dir is None:
            # 默认使用项目根目录下的config文件夹
            self.config_dir = Path(__file__).parent.parent.parent / "config"
        else:
            self.config_dir = Path(config_dir)

        self._cache: Dict[str, ConfigLoadResult] = {}
        self._checksums: Dict[str, str] = {}

    def load_config(self, config_name: str = "grag_config.yaml",
                   force_reload: bool = False) -> Dict[str, Any]:
        """加载配置文件

        Args:
            config_name: 配置文件名
            force_reload: 是否强制重新加载（忽略缓存）

        Returns:
            配置字典

        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: YAML解析错误
        """
        config_path = self.config_dir / config_name

        # 检查缓存
        if not force_reload and config_name in self._cache:
            cached = self._cache[config_name]
            # 检查文件是否被修改
            if config_path.exists() and self._get_file_checksum(config_path) == cached.checksum:
                return cached.config

        # 加载配置文件
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"YAML解析失败: {config_path}") from e

        if raw_config is None:
            raw_config = {}

        # 处理环境变量插值
        processed_config = self._process_env_vars(raw_config)

        # 创建加载结果
        load_result = ConfigLoadResult(
            config=processed_config,
            config_path=config_path,
            loaded_at=datetime.now(),
            checksum=self._get_file_checksum(config_path)
        )

        # 更新缓存
        self._cache[config_name] = load_result

        return processed_config

    def load_multiple_configs(self, config_names: list,
                            merge_strategy: str = "override") -> Dict[str, Any]:
        """加载多个配置文件并合并

        Args:
            config_names: 配置文件名列表
            merge_strategy: 合并策略 ('override' 或 'merge')

        Returns:
            合并后的配置字典
        """
        merged_config = {}

        for config_name in config_names:
            config = self.load_config(config_name)

            if merge_strategy == "override":
                # 完全覆盖
                merged_config.update(config)
            elif merge_strategy == "merge":
                # 深度合并
                merged_config = self._deep_merge(merged_config, config)
            else:
                raise ValueError(f"不支持的合并策略: {merge_strategy}")

        return merged_config

    def get_config_value(self, config: Dict[str, Any], key_path: str,
                        default: Any = None) -> Any:
        """从配置中获取嵌套键的值

        Args:
            config: 配置字典
            key_path: 键路径，用点号分隔，如 "llm_providers.siliconflow.model"
            default: 默认值

        Returns:
            配置值或默认值
        """
        keys = key_path.split('.')
        current = config

        try:
            for key in keys:
                if isinstance(current, dict):
                    current = current[key]
                else:
                    return default
            return current
        except (KeyError, TypeError):
            return default

    def set_config_value(self, config: Dict[str, Any], key_path: str, value: Any) -> None:
        """设置配置中的嵌套键值

        Args:
            config: 配置字典
            key_path: 键路径
            value: 要设置的值
        """
        keys = key_path.split('.')
        current = config

        # 遍历到倒数第二个键
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        # 设置最后一个键的值
        current[keys[-1]] = value

    def _process_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """处理配置中的环境变量插值

        支持的格式：
        - ${ENV_VAR_NAME}
        - ${ENV_VAR_NAME:default_value}

        Args:
            config: 原始配置字典

        Returns:
            处理后的配置字典
        """
        def process_value(value: Any) -> Any:
            if isinstance(value, str):
                return self._interpolate_env_vars(value)
            elif isinstance(value, dict):
                return {k: process_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [process_value(item) for item in value]
            else:
                return value

        return process_value(config)

    def _interpolate_env_vars(self, text: str) -> str:
        """插值替换字符串中的环境变量

        Args:
            text: 包含环境变量占位符的字符串

        Returns:
            替换后的字符串
        """
        import re

        def replace_var(match):
            var_expr = match.group(1)
            if ':' in var_expr:
                var_name, default_value = var_expr.split(':', 1)
            else:
                var_name = var_expr
                default_value = ""

            # 从环境变量获取值
            env_value = os.environ.get(var_name.strip())
            if env_value is not None:
                return env_value
            elif default_value:
                return default_value.strip()
            else:
                # 如果环境变量不存在且没有默认值，保持原样
                return match.group(0)

        # 匹配 ${VAR_NAME} 或 ${VAR_NAME:default} 格式
        pattern = r'\$\{([^}]+)\}'
        return re.sub(pattern, replace_var, text)

    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并两个字典

        Args:
            base: 基础字典
            update: 更新字典

        Returns:
            合并后的字典
        """
        result = base.copy()

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _get_file_checksum(self, file_path: Path) -> str:
        """计算文件的校验和

        Args:
            file_path: 文件路径

        Returns:
            文件的MD5校验和
        """
        import hashlib

        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _get_current_time(self) -> str:
        """获取当前时间字符串

        Returns:
            ISO格式的时间字符串
        """
        from datetime import datetime
        return datetime.now().isoformat()

    def clear_cache(self) -> None:
        """清除配置缓存"""
        self._cache.clear()
        self._checksums.clear()

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return {
            "cached_configs": list(self._cache.keys()),
            "cache_info": {
                name: {
                    "path": str(result.config_path),
                    "loaded_at": result.loaded_at.isoformat(),
                    "checksum": result.checksum[:8] + "..."
                }
                for name, result in self._cache.items()
            }
        }


# 全局配置加载器实例
_default_loader = None


def get_config_loader() -> ConfigLoader:
    """获取默认的配置加载器实例"""
    global _default_loader
    if _default_loader is None:
        _default_loader = ConfigLoader()
    return _default_loader


def load_grag_config(force_reload: bool = False) -> Dict[str, Any]:
    """加载GraphRAG配置文件

    Args:
        force_reload: 是否强制重新加载

    Returns:
        GraphRAG配置字典
    """
    loader = get_config_loader()
    return loader.load_config("grag_config.yaml", force_reload)


def get_config_value(key_path: str, default: Any = None) -> Any:
    """从GraphRAG配置中获取值

    Args:
        key_path: 配置键路径
        default: 默认值

    Returns:
        配置值
    """
    config = load_grag_config()
    loader = get_config_loader()
    return loader.get_config_value(config, key_path, default)