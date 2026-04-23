"""grag.graph_construction.entity_relation_parser

实体/关系抽取结果解析器（Parser）。

职责：
- 将 `EntityRelationExtractor` 返回的 raw 文本（多行字符串）解析为结构化对象
- 支持两类行：实体行（entity）与关系行（relation）
- 兼容 `<|DONE|>` 结束标记，并对异常行做容错收集（errors），避免流程中断

输入示例（raw 文本，每行一条记录）：
    entity<|SEP|>实体名称<|SEP|>类型<|SEP|>描述
    relation<|SEP|>主体<|SEP|>客体<|SEP|>关系描述<|SEP|>关系类型<|SEP|>置信度
    <|DONE|>

输出：
- ParsedEntityRelation(entities=[...], relations=[...], errors=[...])

注意：
- 该解析器只做“语法级解析”（按分隔符拆分），不会进行实体对齐、去重或图谱入库。
- 如果模型输出行字段数量不够/置信度不是整数，解析器会把问题写入 `errors`，并尽量继续解析后续行。
"""


import re
from dataclasses import dataclass
from typing import List, Optional
 
from grag.monitoring.monitoring_manager import get_current_monitor


SEP_TOKEN = "<|SEP|>"
DONE_TOKEN = "<|DONE|>"


def _normalize_separator_tokens(text: str) -> str:
    """兼容模型偶发生成的坏分隔符，减少解析阶段的格式敏感性。"""
    normalized = text or ""
    separator_variants = [
        r"<\|SEP\?>",
        r"<\|SEP\uff1f>",
        r"<\|SEP\uff5c>",
        r"<\|SEP[|!1Il\uff5c\u4e28]>",
        r"<\|SEP\s*\|?\s*>",
    ]
    for pattern in separator_variants:
        normalized = re.sub(pattern, SEP_TOKEN, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<\|\s*DONE\s*\|?\s*>", DONE_TOKEN, normalized, flags=re.IGNORECASE)
    return normalized


@dataclass(frozen=True)
class ParsedEntity:
    """解析后的实体对象。"""

    name: str
    type: str
    description: str


@dataclass(frozen=True)
class ParsedRelation:
    """解析后的关系对象。"""

    subject: str
    object: str
    description: str
    relation_type: str
    confidence: Optional[int]


@dataclass(frozen=True)
class ParsedEntityRelation:
    """解析结果汇总。

    - entities: 解析出的实体列表
    - relations: 解析出的关系列表
    - errors: 解析过程中遇到的异常/格式问题（不会抛异常）
    """

    entities: List[ParsedEntity]
    relations: List[ParsedRelation]
    errors: List[str]


def parse_entity_relation_raw(raw: str) -> ParsedEntityRelation:
    """解析实体/关系抽取的 raw 文本为结构化对象。

    Args:
        raw: LLM 返回的原始多行文本。

    Returns:
        ParsedEntityRelation: 解析后的实体列表、关系列表与错误列表。

    解析规则：
    - 忽略空行
    - 遇到 `<|DONE|>` 立即停止解析
    - `entity` 行至少 4 段：entity / name / type / description
    - `relation` 行至少 6 段：relation / subject / object / description / relation_type / confidence
    - 解析异常不抛出，记录到 errors 并尽量继续处理后续行
    """

    entities: List[ParsedEntity] = []
    relations: List[ParsedRelation] = []
    errors: List[str] = []

    text = _normalize_separator_tokens((raw or "").strip())
    if not text:
        monitor = get_current_monitor()
        if monitor is not None:
            monitor.observe("entity_relation_parsing.entities", 0.0)
            monitor.observe("entity_relation_parsing.relations", 0.0)
            monitor.observe("entity_relation_parsing.parse_errors", 0.0)
        return ParsedEntityRelation(entities=entities, relations=relations, errors=errors)

    for idx, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line == DONE_TOKEN:
            break

        # 按 `<|SEP|>` 拆分字段。
        parts = [p.strip() for p in line.split(SEP_TOKEN)]
        if not parts:
            continue

        kind = parts[0]
        if kind == "entity":
            if len(parts) < 4:
                errors.append(f"line {idx}: invalid entity fields count={len(parts)}")
                continue
            name = parts[1]
            etype = parts[2]

            # description 允许包含分隔符：将第 4 段起的所有内容拼回。
            desc = SEP_TOKEN.join(parts[3:]).strip()
            if not name or not etype:
                errors.append(f"line {idx}: entity missing name/type")
                continue
            entities.append(ParsedEntity(name=name, type=etype, description=desc))
            continue

        if kind == "relation":
            if len(parts) < 6:
                errors.append(f"line {idx}: invalid relation fields count={len(parts)}")
                continue
            subj = parts[1]
            obj = parts[2]
            desc = parts[3]
            rtype = parts[4]

            # 置信度理论上应为 1-10 的整数；解析失败时记入 errors。
            conf_raw = SEP_TOKEN.join(parts[5:]).strip()
            conf: Optional[int]
            try:
                conf = int(conf_raw)
            except Exception:
                conf = None
                errors.append(f"line {idx}: invalid confidence '{conf_raw}'")

            if not subj or not obj:
                errors.append(f"line {idx}: relation missing subject/object")
                continue
            relations.append(
                ParsedRelation(
                    subject=subj,
                    object=obj,
                    description=desc,
                    relation_type=rtype,
                    confidence=conf,
                )
            )
            continue

        errors.append(f"line {idx}: unknown kind '{kind}'")

    monitor = get_current_monitor()
    if monitor is not None:
        monitor.observe("entity_relation_parsing.entities", float(len(entities)))
        monitor.observe("entity_relation_parsing.relations", float(len(relations)))
        monitor.observe("entity_relation_parsing.parse_errors", float(len(errors)))
    return ParsedEntityRelation(entities=entities, relations=relations, errors=errors)
