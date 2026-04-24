"""检索计划执行模块。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agent.telemetry import emit_event
from grag.observability import get_current_trace_recorder


RAG_CONTEXT_RE = re.compile(
    r"^\[RAG_CONTEXT\]\s*(group_id|doc_id)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)

ALLOWED_MODES = {
    "chunks_vector",
    "chunks_keyword",
    "entities",
    "relations",
    "relations_by_entities",
    "entities_by_relations",
}

MAX_COMPACT_TEXT_CHARS = 320


def _start_invocation(
    *,
    kind: str,
    name: str,
    input_payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    recorder = get_current_trace_recorder()
    if recorder is None:
        return None
    invocation_id = f"{kind}:{name}:{uuid.uuid4().hex[:10]}"
    recorder.start_invocation(
        kind=kind,
        name=name,
        invocation_id=invocation_id,
        input_payload=input_payload or {},
        metadata=metadata or {},
    )
    return invocation_id


def _finish_invocation(
    invocation_id: str | None,
    *,
    status: str = "completed",
    output_payload: dict[str, Any] | None = None,
    error: Exception | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if invocation_id is None:
        return
    recorder = get_current_trace_recorder()
    if recorder is None:
        return
    if error is not None or error_message:
        recorder.finish_invocation(
            invocation_id,
            status="failed" if status == "completed" else status,
            error={
                "error_type": type(error).__name__ if error is not None else "RuntimeError",
                "message": str(error) if error is not None else str(error_message or ""),
            },
            metadata=metadata or {},
        )
        return
    recorder.finish_invocation(
        invocation_id,
        status=status,
        output_payload=output_payload or {},
        metadata=metadata or {},
    )


def extract_rag_context(text: str) -> tuple[str, str, str]:
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
    payload = json.loads((plan_json or "").strip())
    if not isinstance(payload, dict):
        raise ValueError("plan_json 必须是 JSON 对象")

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("plan_json.steps 必须是非空数组")
    return payload


def get_plan_schema() -> dict[str, Any]:
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
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _find_candidate_lists(payload: Any) -> list[list[dict[str, Any]]]:
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
    candidate_lists = _find_candidate_lists(payload)
    if not candidate_lists:
        return []

    source = max(candidate_lists, key=len)
    items: list[dict[str, Any]] = []
    for item in source:
        text = _first_non_empty(item, "text", "content", "chunk_text", "excerpt", "snippet")
        document_name = _first_non_empty(item, "document_name", "doc_name", "doc_title", "doc_id")
        chunk_id = _first_non_empty(item, "chunk_id", "id")
        entity_name = _first_non_empty(item, "canonical_name", "name", "entity_name")
        relation_value = _first_non_empty(item, "triple", "relation", "predicate", "relation_triple")
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


def _compact_text(text: str, *, limit: int = MAX_COMPACT_TEXT_CHARS) -> str:
    content = " ".join(str(text or "").split())
    if len(content) <= limit:
        return content
    return f"{content[: max(0, limit - 1)].rstrip()}…"


def build_compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": item.get("type"),
        "document_name": item.get("document_name"),
        "doc_id": item.get("doc_id"),
        "chunk_id": item.get("chunk_id"),
        "entity_name": item.get("entity_name"),
        "relation": item.get("relation"),
        "score": item.get("score"),
        "mode": item.get("mode"),
        "label": item.get("label"),
        "text": _compact_text(str(item.get("text") or "")),
    }


def build_compact_result(
    result: dict[str, Any],
    *,
    max_items: int = 5,
    include_steps: bool = True,
) -> dict[str, Any]:
    steps = []
    if include_steps:
        for step in result.get("steps") or []:
            steps.append(
                {
                    "step": step.get("step"),
                    "label": step.get("label"),
                    "mode": step.get("mode"),
                    "query": step.get("query"),
                    "raw_count": step.get("raw_count"),
                }
            )

    return {
        "result_id": result.get("result_id"),
        "query": result.get("query"),
        "group_id": result.get("group_id"),
        "doc_id": result.get("doc_id"),
        "steps": steps,
        "items": [build_compact_item(item) for item in (result.get("items") or [])[: max_items]],
        "errors": result.get("errors") or [],
    }


def _to_csv(values: Any) -> str:
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
    return f"scripts/{mode}.py"


def _looks_like_error_text(raw_text: str) -> bool:
    text = str(raw_text or "").lstrip()
    return text.startswith("❌") or text.startswith("错误") or text.startswith("Error:")


def execute_retrieval_plan(
    *,
    skill_manager: Any,
    query: str,
    plan_json: str,
    group_id: str = "",
    doc_id: str = "",
) -> dict[str, Any]:
    inferred_group_id, inferred_doc_id, clean_query = extract_rag_context(query)
    effective_group_id = (group_id or inferred_group_id).strip()
    effective_doc_id = (doc_id or inferred_doc_id).strip()
    effective_query = clean_query or str(query or "").strip()

    plan_invocation_id = _start_invocation(
        kind="retrieval_plan",
        name="execute_retrieval_plan",
        input_payload={
            "query": effective_query,
            "group_id": effective_group_id,
            "doc_id": effective_doc_id,
            "plan_preview": str(plan_json or "")[:1200],
        },
    )

    if not effective_group_id:
        message = "缺少 group_id"
        _finish_invocation(plan_invocation_id, error_message=message)
        raise ValueError(message)

    plan = parse_plan(plan_json)
    emit_event(
        "retrieval.plan.start",
        {
            "query": effective_query,
            "group_id": effective_group_id,
            "doc_id": effective_doc_id or None,
            "step_count": len(plan["steps"]),
        },
    )

    step_outputs: list[dict[str, Any]] = []
    merged_items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, step in enumerate(plan["steps"], start=1):
        step_invocation_id = _start_invocation(
            kind="retrieval_step",
            name=f"plan_step_{index}",
            input_payload={
                "step": index,
                "step_payload": step,
                "group_id": effective_group_id,
                "doc_id": effective_doc_id,
                "query": effective_query,
            },
        )
        if not isinstance(step, dict):
            error_text = "step 必须是对象"
            errors.append({"step": index, "error": error_text})
            emit_event("retrieval.step.error", {"step": index, "error": error_text})
            _finish_invocation(step_invocation_id, error_message=error_text)
            continue

        mode = str(step.get("mode", "")).strip()
        label = str(step.get("label") or f"step_{index}").strip()
        step_query = str(step.get("query") or effective_query or "").strip()
        emit_event(
            "retrieval.step.start",
            {
                "step": index,
                "mode": mode,
                "label": label,
                "query": step_query,
            },
        )

        try:
            script_name = _script_name_for_mode(mode)
            script_args = _build_script_args(
                group_id=effective_group_id,
                doc_id=effective_doc_id,
                default_query=effective_query,
                step=step,
            )

            script_invocation_id = _start_invocation(
                kind="retrieval_script",
                name=mode,
                input_payload={
                    "step": index,
                    "mode": mode,
                    "label": label,
                    "script_name": script_name,
                    "script_args": script_args,
                },
            )
            raw = skill_manager.execute_skill_script("rag-retrieval", script_name, script_args)
            raw_text = str(raw or "")
            if _looks_like_error_text(raw_text):
                errors.append({"step": index, "mode": mode, "error": raw_text})
                emit_event(
                    "retrieval.step.error",
                    {"step": index, "mode": mode, "label": label, "error": raw_text},
                )
                _finish_invocation(
                    script_invocation_id,
                    status="failed",
                    error_message=raw_text,
                    metadata={"step": index, "mode": mode, "label": label},
                )
                _finish_invocation(step_invocation_id, status="failed", error_message=raw_text)
                continue

            payload = json.loads(raw_text.strip())
            items = normalize_items(payload, mode=mode, label=label)
            merged_items.extend(items)
            step_output = {
                "step": index,
                "label": label,
                "mode": mode,
                "query": step_query,
                "items": items,
                "raw_count": len(items),
            }
            step_outputs.append(step_output)
            emit_event(
                "retrieval.step.end",
                {
                    "step": index,
                    "mode": mode,
                    "label": label,
                    "query": step_query,
                    "raw_count": len(items),
                },
            )
            _finish_invocation(
                script_invocation_id,
                status="completed",
                output_payload={
                    "step": index,
                    "mode": mode,
                    "label": label,
                    "raw_count": len(items),
                    "raw_preview": raw_text[:1200],
                },
            )
            _finish_invocation(
                step_invocation_id,
                status="completed",
                output_payload={
                    "step": index,
                    "mode": mode,
                    "label": label,
                    "item_count": len(items),
                    "items_preview": items[:5],
                },
            )
        except Exception as exc:
            errors.append({"step": index, "mode": mode, "error": str(exc)})
            emit_event(
                "retrieval.step.error",
                {"step": index, "mode": mode, "label": label, "error": str(exc)},
            )
            _finish_invocation(step_invocation_id, error=exc, metadata={"step": index, "mode": mode, "label": label})

    deduped_items = dedupe_items(merged_items)
    return_limit = int(plan.get("return_limit", 12))
    result = {
        "result_id": uuid.uuid4().hex,
        "query": effective_query,
        "group_id": effective_group_id,
        "doc_id": effective_doc_id or None,
        "plan": plan,
        "steps": step_outputs,
        "items": deduped_items[: max(1, return_limit)],
        "errors": errors,
    }
    emit_event(
        "retrieval.plan.end",
        {
            "step_count": len(step_outputs),
            "item_count": len(result["items"]),
            "error_count": len(errors),
        },
    )
    _finish_invocation(
        plan_invocation_id,
        status="completed",
        output_payload={
            "step_count": len(step_outputs),
            "item_count": len(result["items"]),
            "error_count": len(errors),
            "items_preview": result["items"][:8],
        },
    )
    return result
