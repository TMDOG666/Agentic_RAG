from __future__ import annotations

from api.presentation.trace_dto import map_agent_event_to_dto, map_pipeline_checkpoint_to_step


def test_agent_event_dto_fills_timestamps_from_timestamp():
    dto = map_agent_event_to_dto(
        {
            "type": "tool.end",
            "tool_name": "search",
            "timestamp": "2026-04-23T10:00:00+00:00",
            "latency_ms": 123,
        },
        trace_id="trace-1",
    )

    assert dto.step.trace_id == "trace-1"
    assert dto.step.status == "completed"
    assert dto.step.started_at == "2026-04-23T10:00:00+00:00"
    assert dto.step.updated_at == "2026-04-23T10:00:00+00:00"
    assert dto.step.ended_at == "2026-04-23T10:00:00+00:00"


def test_pipeline_checkpoint_dto_uses_unified_fields():
    step = map_pipeline_checkpoint_to_step(
        "entity_alignment",
        {
            "status": "done",
            "updated_at": "2026-04-23T10:00:00+00:00",
            "payload": {
                "latency_ms": 456,
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        },
        trace_id="trace-2",
    )

    assert step.trace_id == "trace-2"
    assert step.status == "completed"
    assert step.started_at == "2026-04-23T10:00:00+00:00"
    assert step.updated_at == "2026-04-23T10:00:00+00:00"
    assert step.ended_at == "2026-04-23T10:00:00+00:00"
    assert step.tokens is not None
    assert step.tokens.total_tokens == 30
