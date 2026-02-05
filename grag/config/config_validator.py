"""grag.config.config_validator

配置验证器（Configuration Validator）

职责：
- 验证配置文件的结构和类型
- 检查必需的配置项
- 验证配置值的合理性
- 提供详细的验证错误信息

说明：
- 支持模式验证（schema validation）
- 提供配置建议和修复建议
- 支持自定义验证规则
"""

import re
from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass
from enum import Enum


class ValidationLevel(Enum):
    """验证级别"""
    ERROR = "error"      # 必须修复的错误
    WARNING = "warning"  # 建议修复的警告
    INFO = "info"        # 信息提示


@dataclass
class ValidationResult:
    """验证结果"""
    level: ValidationLevel
    field_path: str
    message: str
    suggestion: Optional[str] = None
    actual_value: Any = None
    expected_value: Any = None


class ConfigValidator:
    """配置验证器"""

    def __init__(self):
        """初始化验证器"""
        self._custom_validators: Dict[str, Callable] = {}

    def validate_config(self, config: Dict[str, Any]) -> List[ValidationResult]:
        """验证完整配置

        Args:
            config: 配置字典

        Returns:
            验证结果列表
        """
        results = []

        # 验证顶级结构
        results.extend(self._validate_top_level_structure(config))

        # 验证各个组件配置
        if "llm_providers" in config:
            results.extend(self._validate_llm_providers(config["llm_providers"]))

        if "embedding_providers" in config:
            results.extend(self._validate_embedding_providers(config["embedding_providers"]))

        if "reranker_providers" in config:
            results.extend(self._validate_reranker_providers(config["reranker_providers"]))

        if "vector_databases" in config:
            results.extend(self._validate_vector_databases(config["vector_databases"]))

        if "graph_databases" in config:
            results.extend(self._validate_graph_databases(config["graph_databases"]))

        if "relational_databases" in config:
            results.extend(self._validate_relational_databases(config["relational_databases"]))

        if "system" in config:
            results.extend(self._validate_system_config(config["system"]))

        if "preprocessing" in config:
            results.extend(self._validate_preprocessing_config(config["preprocessing"]))

        if "graph_construction" in config:
            results.extend(self._validate_graph_construction_config(config["graph_construction"]))

        if "retrieval" in config:
            results.extend(self._validate_retrieval_config(config["retrieval"]))

        # 执行自定义验证器
        for field_path, validator in self._custom_validators.items():
            try:
                custom_results = validator(config, field_path)
                if custom_results:
                    results.extend(custom_results)
            except Exception as e:
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=field_path,
                    message=f"自定义验证器执行失败: {e}",
                    suggestion="检查自定义验证器实现"
                ))

        return results

    def add_custom_validator(self, field_path: str, validator: Callable) -> None:
        """添加自定义验证器

        Args:
            field_path: 字段路径
            validator: 验证函数，签名: (config, field_path) -> List[ValidationResult]
        """
        self._custom_validators[field_path] = validator

    def _validate_top_level_structure(self, config: Dict[str, Any]) -> List[ValidationResult]:
        """验证顶级配置结构"""
        results = []

        required_fields = [
            "llm_provider", "embedding_provider", "vector_db_provider",
            "graph_db_provider", "relational_db_provider"
        ]

        for field in required_fields:
            if field not in config:
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=field,
                    message=f"缺少必需的配置字段: {field}",
                    suggestion=f"请在配置中添加 {field} 字段"
                ))

        # 验证提供商引用
        provider_fields = {
            "llm_provider": "llm_providers",
            "embedding_provider": "embedding_providers",
            "reranker_provider": "reranker_providers",
            "vector_db_provider": "vector_databases",
            "graph_db_provider": "graph_databases",
            "relational_db_provider": "relational_databases"
        }

        for provider_field, providers_field in provider_fields.items():
            if provider_field in config and providers_field in config:
                provider_name = config[provider_field]
                if provider_name not in config[providers_field]:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=provider_field,
                        message=f"引用的提供商 '{provider_name}' 在 {providers_field} 中不存在",
                        suggestion=f"请在 {providers_field} 中添加 '{provider_name}' 配置或修改 {provider_field} 的值",
                        actual_value=provider_name
                    ))

        return results

    def _validate_llm_providers(self, providers: Dict[str, Any]) -> List[ValidationResult]:
        """验证LLM提供商配置"""
        results = []
        required_fields = ["model", "base_url", "api_key_env"]

        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"llm_providers.{provider_name}",
                    message=f"LLM提供商配置必须是字典类型",
                    actual_value=type(provider_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 检查必需字段
            for field in required_fields:
                if field not in provider_config:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"llm_providers.{provider_name}.{field}",
                        message=f"缺少必需字段: {field}",
                        suggestion=f"为 {provider_name} 提供商添加 {field} 配置"
                    ))

            # 验证数值类型
            if "temperature" in provider_config:
                temp = provider_config["temperature"]
                if not isinstance(temp, (int, float)) or not (0 <= temp <= 2):
                    results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field_path=f"llm_providers.{provider_name}.temperature",
                        message="temperature 应在 0-2 范围内",
                        actual_value=temp,
                        expected_value="0.0-2.0"
                    ))

            if "max_tokens" in provider_config:
                max_tokens = provider_config["max_tokens"]
                if not isinstance(max_tokens, int) or max_tokens <= 0:
                    results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field_path=f"llm_providers.{provider_name}.max_tokens",
                        message="max_tokens 应为正整数",
                        actual_value=max_tokens,
                        expected_value="正整数"
                    ))

        return results

    def _validate_embedding_providers(self, providers: Dict[str, Any]) -> List[ValidationResult]:
        """验证向量嵌入提供商配置"""
        results = []
        required_fields = ["model", "dimension"]

        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"embedding_providers.{provider_name}",
                    message="嵌入提供商配置必须是字典类型",
                    actual_value=type(provider_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 检查必需字段
            for field in required_fields:
                if field not in provider_config:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"embedding_providers.{provider_name}.{field}",
                        message=f"缺少必需字段: {field}",
                        suggestion=f"为 {provider_name} 嵌入提供商添加 {field} 配置"
                    ))

            # 验证维度
            if "dimension" in provider_config:
                dim = provider_config["dimension"]
                if not isinstance(dim, int) or dim <= 0:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"embedding_providers.{provider_name}.dimension",
                        message="dimension 必须为正整数",
                        actual_value=dim,
                        expected_value="正整数"
                    ))

        return results

    def _validate_reranker_providers(self, providers: Dict[str, Any]) -> List[ValidationResult]:
        """验证重排序提供商配置"""
        results = []

        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"reranker_providers.{provider_name}",
                    message="重排序提供商配置必须是字典类型",
                    actual_value=type(provider_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 验证top_k
            if "top_k" in provider_config:
                top_k = provider_config["top_k"]
                if not isinstance(top_k, int) or top_k <= 0:
                    results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field_path=f"reranker_providers.{provider_name}.top_k",
                        message="top_k 应为正整数",
                        actual_value=top_k,
                        expected_value="正整数"
                    ))

        return results

    def _validate_vector_databases(self, databases: Dict[str, Any]) -> List[ValidationResult]:
        """验证向量数据库配置"""
        results = []

        for db_name, db_config in databases.items():
            if not isinstance(db_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"vector_databases.{db_name}",
                    message="向量数据库配置必须是字典类型",
                    actual_value=type(db_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 验证连接参数
            if db_name == "milvus":
                required_fields = ["host", "port"]
            elif db_name == "qdrant":
                required_fields = ["host", "port"]
            elif db_name == "pinecone":
                required_fields = ["api_key_env", "index_name"]
            else:
                continue

            for field in required_fields:
                if field not in db_config:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"vector_databases.{db_name}.{field}",
                        message=f"缺少必需字段: {field}",
                        suggestion=f"为 {db_name} 数据库添加 {field} 配置"
                    ))

        return results

    def _validate_graph_databases(self, databases: Dict[str, Any]) -> List[ValidationResult]:
        """验证图数据库配置"""
        results = []

        for db_name, db_config in databases.items():
            if not isinstance(db_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"graph_databases.{db_name}",
                    message="图数据库配置必须是字典类型",
                    actual_value=type(db_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 验证连接参数
            if db_name == "neo4j":
                required_fields = ["uri", "user", "password_env"]
            elif db_name == "nebula":
                required_fields = ["host", "port", "user", "password_env"]
            else:
                continue

            for field in required_fields:
                if field not in db_config:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"graph_databases.{db_name}.{field}",
                        message=f"缺少必需字段: {field}",
                        suggestion=f"为 {db_name} 数据库添加 {field} 配置"
                    ))

        return results

    def _validate_relational_databases(self, databases: Dict[str, Any]) -> List[ValidationResult]:
        """验证关系数据库配置"""
        results = []

        for db_name, db_config in databases.items():
            if not isinstance(db_config, dict):
                results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field_path=f"relational_databases.{db_name}",
                    message="关系数据库配置必须是字典类型",
                    actual_value=type(db_config).__name__,
                    expected_value="dict"
                ))
                continue

            # 验证连接参数
            if db_name in ["postgres", "mysql"]:
                required_fields = ["host", "port", "database", "user", "password_env"]
            elif db_name == "sqlite":
                required_fields = ["database_path"]
            else:
                continue

            for field in required_fields:
                if field not in db_config:
                    results.append(ValidationResult(
                        level=ValidationLevel.ERROR,
                        field_path=f"relational_databases.{db_name}.{field}",
                        message=f"缺少必需字段: {field}",
                        suggestion=f"为 {db_name} 数据库添加 {field} 配置"
                    ))

        return results

    def _validate_system_config(self, system_config: Dict[str, Any]) -> List[ValidationResult]:
        """验证系统配置"""
        results = []

        # 验证工作目录
        if "workspace_dir" in system_config:
            workspace_dir = system_config["workspace_dir"]
            if not isinstance(workspace_dir, str):
                results.append(ValidationResult(
                    level=ValidationLevel.WARNING,
                    field_path="system.workspace_dir",
                    message="workspace_dir 应为字符串类型",
                    actual_value=type(workspace_dir).__name__,
                    expected_value="str"
                ))

        return results

    def _validate_preprocessing_config(self, preprocessing_config: Dict[str, Any]) -> List[ValidationResult]:
        """验证预处理配置"""
        results = []

        # 验证文件大小限制
        if "document_processing" in preprocessing_config:
            doc_config = preprocessing_config["document_processing"]
            if "max_file_size" in doc_config:
                max_size = doc_config["max_file_size"]
                if isinstance(max_size, str):
                    # 解析文件大小字符串，如 "50MB"
                    if not re.match(r'^\d+(?:B|KB|MB|GB)$', max_size.upper()):
                        results.append(ValidationResult(
                            level=ValidationLevel.WARNING,
                            field_path="preprocessing.document_processing.max_file_size",
                            message="max_file_size 格式应为数字+单位(B/KB/MB/GB)",
                            actual_value=max_size,
                            expected_value="如: 50MB"
                        ))

        return results

    def _validate_graph_construction_config(self, graph_config: Dict[str, Any]) -> List[ValidationResult]:
        """验证图构建配置"""
        results = []

        # 验证置信度阈值
        confidence_fields = [
            "entity_extraction.confidence_threshold",
            "relation_extraction.confidence_threshold"
        ]

        for field_path in confidence_fields:
            threshold = self._get_nested_value(graph_config, field_path)
            if threshold is not None and (not isinstance(threshold, (int, float)) or not (0 <= threshold <= 1)):
                results.append(ValidationResult(
                    level=ValidationLevel.WARNING,
                    field_path=f"graph_construction.{field_path}",
                    message="置信度阈值应在 0-1 范围内",
                    actual_value=threshold,
                    expected_value="0.0-1.0"
                ))

        return results

    def _validate_retrieval_config(self, retrieval_config: Dict[str, Any]) -> List[ValidationResult]:
        """验证检索配置"""
        results = []

        # 验证权重配置
        if "fusion_search" in retrieval_config:
            fusion_config = retrieval_config["fusion_search"]
            if "weights" in fusion_config:
                weights = fusion_config["weights"]
                if isinstance(weights, dict):
                    total_weight = sum(weights.values())
                    if not abs(total_weight - 1.0) < 0.001:  # 允许小数点误差
                        results.append(ValidationResult(
                            level=ValidationLevel.WARNING,
                            field_path="retrieval.fusion_search.weights",
                            message="融合检索权重之和应为 1.0",
                            actual_value=total_weight,
                            expected_value="1.0"
                        ))

        return results

    def _get_nested_value(self, config: Dict[str, Any], field_path: str) -> Any:
        """获取嵌套字典中的值"""
        keys = field_path.split('.')
        current = config

        try:
            for key in keys:
                if isinstance(current, dict):
                    current = current[key]
                else:
                    return None
            return current
        except KeyError:
            return None

    def get_validation_summary(self, results: List[ValidationResult]) -> Dict[str, Any]:
        """获取验证结果摘要"""
        summary = {
            "total": len(results),
            "errors": 0,
            "warnings": 0,
            "infos": 0,
            "error_messages": [],
            "warning_messages": [],
            "info_messages": []
        }

        for result in results:
            if result.level == ValidationLevel.ERROR:
                summary["errors"] += 1
                summary["error_messages"].append(f"{result.field_path}: {result.message}")
            elif result.level == ValidationLevel.WARNING:
                summary["warnings"] += 1
                summary["warning_messages"].append(f"{result.field_path}: {result.message}")
            elif result.level == ValidationLevel.INFO:
                summary["infos"] += 1
                summary["info_messages"].append(f"{result.field_path}: {result.message}")

        return summary


def validate_grag_config(config: Optional[Dict[str, Any]] = None) -> List[ValidationResult]:
    """验证GraphRAG配置

    Args:
        config: 要验证的配置，如果为None则自动加载默认配置

    Returns:
        验证结果列表
    """
    from .config_loader import load_grag_config

    if config is None:
        config = load_grag_config()

    validator = ConfigValidator()
    return validator.validate_config(config)


def print_validation_results(results: List[ValidationResult]) -> None:
    """打印验证结果"""
    if not results:
        print("配置验证通过")
        return

    validator = ConfigValidator()
    summary = validator.get_validation_summary(results)

    print(f"\n配置验证结果: {summary['total']} 个问题")
    print(f"错误: {summary['errors']} 个")
    print(f"警告: {summary['warnings']} 个")
    print(f"信息: {summary['infos']} 个")

    if summary['error_messages']:
        print("\n错误详情:")
        for msg in summary['error_messages']:
            print(f"  • {msg}")

    if summary['warning_messages']:
        print("\n警告详情:")
        for msg in summary['warning_messages']:
            print(f"  • {msg}")

    if summary['info_messages']:
        print("\n信息详情:")
        for msg in summary['info_messages']:
            print(f"  • {msg}")