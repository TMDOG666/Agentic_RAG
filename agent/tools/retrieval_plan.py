"""检索计划模块。

该模块负责：

- 解析对话中的 RAG 上下文
- 定义检索计划 schema
- 校验 plan_json
- 把计划步骤转换成脚本参数
- 执行多步检索
- 统一归一化结果并去重
"""

from __future__ import annotations

import json
import re
from typing import Any


# 从注入到用户问题中的上下文行提取 group_id / doc_id。
RAG_CONTEXT_RE = re.compile(
    r"^\[RAG_CONTEXT\]\s*(group_id|doc_id)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)

# 当前允许 Agent 在计划中使用的检索模式。
ALLOWED_MODES = {
    "chunks_vector",
    "chunks_keyword",
    "entities",
    "relations",
    "relations_by_entities",
    "entities_by_relations",
}


def extract_rag_context(text: str) -> tuple[str, str, str]:
    """从原始问题文本中提取 RAG 上下文，并返回净化后的 query。"""
    group_id = ""
    doc_id = ""
    kept_lines: list[str] = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        match = RAG_CONTEXT_RE.match(line)
        if not match:
            kept_lines.append(raw_line)
            continue
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key == "group_id" and not group_id:
            group_id = value
        elif key == "doc_id" and not doc_id:
            doc_id = value

    return group_id, doc_id, "\n".join(kept_lines).strip()


def parse_plan(plan_json: str) -> dict[str, Any]:
    """把字符串形式的检索计划解析为字典，并做最基础的结构校验。"""
    payload = json.loads((plan_json or "").strip())
    if not isinstance(payload, dict):
        raise ValueError("plan_json 必须是 JSON 对象")

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("plan_json.steps 必须是非空数组")
    return payload


def get_plan_schema() -> dict[str, Any]:
    """返回检索计划模块的 JSON schema，供 Agent 组织 plan_json 时参考。"""
    return {
        "type": "object",
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"enum": sorted(ALLOWED_MODES)},
                        "label": {"type": "string"},
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1},
                        "limit": {"type": "integer", "minimum": 1},
                        "doc_id": {"type": "string"},
                        "entity_names": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                        "relation_ids": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                        "relation_triples": {"type": "array"},
                        "output_fields": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                    },
                },
            },
            "return_limit": {"type": "integer", "minimum": 1},
        },
    }


def _first_non_empty(item: dict[str, Any], *keys: str) -> Any:
    """按顺序读取候选字段，返回第一个非空值。"""
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _find_candidate_lists(payload: Any) -> list[list[dict[str, Any]]]:
    """在返回 JSON 中递归搜索最像结果列表的候选列表。"""
    found: list[list[dict[str, Any]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if node and all(isinstance(x, dict) for x in node):
                found.append(node)
                return
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return found


def normalize_items(payload: Any, *, mode: str, label: str) -> list[dict[str, Any]]:
    """把不同检索模式的原始 JSON 归一化成统一证据结构。"""
    candidate_lists = _find_candidate_lists(payload)
    if not candidate_lists:
        return []

    # 通常最长的 dict 列表最接近实际召回结果。
    source = max(candidate_lists, key=len)
    items: list[dict[str, Any]] = []
    for item in source:
        text = _first_non_empty(item, "text", "content", "chunk_text", "excerpt", "snippet")
        document_name = _first_non_empty(item, "document_name", "doc_name", "doc_title", "doc_id")
        chunk_id = _first_non_empty(item, "chunk_id", "id")
        entity_name = _first_non_empty(item, "canonical_name", "name", "entity_name")
        relation_value = _first_non_empty(
            item,
            "triple",
            "relation",
            "predicate",
            "relation_triple",
        )
        score = _first_non_empty(item, "score", "distance", "similarity")
        items.append(
            {
                "type": "chunk" if text else ("relation" if relation_value else "entity"),
                "document_name": document_name,
                "doc_id": item.get("doc_id"),
                "chunk_id": chunk_id,
                "text": text,
                "entity_name": entity_name,
                "relation": relation_value,
                "score": score,
                "mode": mode,
                "label": label,
                "raw": item,
            }
        )
    return items


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """基于核心证据字段做去重，避免多步检索返回重复结果。"""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for item in items:
        key = json.dumps(
            {
                "mode": item.get("mode"),
                "doc_id": item.get("doc_id"),
                "chunk_id": item.get("chunk_id"),
                "text": item.get("text"),
                "entity_name": item.get("entity_name"),
                "relation": item.get("relation"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _to_csv(values: Any) -> str:
    """把字符串或字符串列表统一转成逗号分隔形式。"""
    if isinstance(values, list):
        return ",".join(str(v).strip() for v in values if str(v).strip())
    return str(values or "").strip()


def _build_script_args(
    *,
    group_id: str,
    doc_id: str,
    default_query: str,
    step: dict[str, Any],
) -> str:
    """根据计划 step 构造对应检索脚本的命令行参数。"""
    mode = str(step.get("mode", "")).strip()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"不支持的检索模式: {mode}")

    parts = [f"--group-id {group_id}"]
    effective_doc_id = str(step.get("doc_id") or doc_id or "").strip()
    if effective_doc_id:
        parts.append(f"--doc-id {effective_doc_id}")

    if mode in {"chunks_vector", "chunks_keyword", "entities", "relations"}:
        query = str(step.get("query") or default_query or "").strip()
        if not query:
            raise ValueError(f"模式 {mode} 必须提供 query")
        safe_query = query.replace('"', '\\"')
        parts.append(f'--query "{safe_query}"')
        parts.append(f"--top-k {int(step.get('top_k', 5))}")
        output_fields = _to_csv(step.get("output_fields"))
        if output_fields and mode in {"entities", "relations"}:
            parts.append(f"--output-fields {output_fields}")
    elif mode == "relations_by_entities":
        entity_names = _to_csv(step.get("entity_names"))
        if not entity_names:
            raise ValueError("模式 relations_by_entities 必须提供 entity_names")
        parts.append(f"--entity-names {entity_names}")
        parts.append(f"--limit {int(step.get('limit', 50))}")
    elif mode == "entities_by_relations":
        relation_ids = _to_csv(step.get("relation_ids"))
        relation_triples = step.get("relation_triples")
        if not relation_ids and not relation_triples:
            raise ValueError("模式 entities_by_relations 必须提供 relation_ids 或 relation_triples")
        if relation_ids:
            parts.append(f"--relation-ids {relation_ids}")
        if relation_triples:
            safe_json = json.dumps(relation_triples, ensure_ascii=False).replace('"', '\\"')
            parts.append(f'--relation-triples-json "{safe_json}"')
        parts.append(f"--limit {int(step.get('limit', 50))}")

    return " ".join(parts)


def _script_name_for_mode(mode: str) -> str:
    """按约定把检索模式映射为脚本路径。"""
    return f"scripts/{mode}.py"


def execute_retrieval_plan(
    *,
    skill_manager: Any,
    query: str,
    plan_json: str,
    group_id: str = "",
    doc_id: str = "",
) -> dict[str, Any]:
    """执行 Agent 制定的多步检索计划，并返回统一证据结果。"""
    inferred_group_id, inferred_doc_id, clean_query = extract_rag_context(query)
    effective_group_id = (group_id or inferred_group_id).strip()
    effective_doc_id = (doc_id or inferred_doc_id).strip()
    effective_query = clean_query or str(query or "").strip()

    if not effective_group_id:
        raise ValueError("缺少 group_id")

    plan = parse_plan(plan_json)
    step_outputs: list[dict[str, Any]] = []
    merged_items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, step in enumerate(plan["steps"], start=1):
        if not isinstance(step, dict):
            errors.append({"step": index, "error": "step 必须是对象"})
            continue

        try:
            mode = str(step.get("mode", "")).strip()
            label = str(step.get("label") or f"step_{index}").strip()
            script_name = _script_name_for_mode(mode)
            script_args = _build_script_args(
                group_id=effective_group_id,
                doc_id=effective_doc_id,
                default_query=effective_query,
                step=step,
            )
            raw = skill_manager.execute_skill_script("rag-retrieval", script_name, script_args)

            # 底层脚本执行失败时，保留错误并继续执行后续 step。
            raw_text = str(raw).lstrip()
            if raw_text.startswith("❌") or raw_text.startswith("鉂"):
                errors.append({"step": index, "mode": mode, "error": str(raw)})
                continue

            payload = json.loads((raw or "").strip())
            items = normalize_items(payload, mode=mode, label=label)
            merged_items.extend(items)
            step_outputs.append(
                {
                    "step": index,
                    "label": label,
                    "mode": mode,
                    "query": step.get("query") or effective_query,
                    "items": items,
                    "raw_count": len(items),
                }
            )
        except Exception as exc:
            errors.append({"step": index, "mode": step.get("mode"), "error": str(exc)})

    deduped_items = dedupe_items(merged_items)
    return_limit = int(plan.get("return_limit", 12))
    return {
        "query": effective_query,
        "group_id": effective_group_id,
        "doc_id": effective_doc_id or None,
        "plan": plan,
        "steps": step_outputs,
        "items": deduped_items[: max(1, return_limit)],
        "errors": errors,
    }
