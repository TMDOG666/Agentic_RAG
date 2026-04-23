from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Iterator

from agent.agent.agent_with_skills import run_once, stream_once
from grag.observability import TraceRecorder, bind_trace_recorder

from api.presentation.trace_dto import map_agent_event_to_dto
from api.schemas.agent import AgentRunIn, AgentRunOut


class AgentService:
    def _build_prompt(self, payload: AgentRunIn) -> str:
        injected_lines: list[str] = []
        if payload.group_id:
            injected_lines.append(f"[RAG_CONTEXT] group_id={payload.group_id}")
        if payload.doc_id:
            injected_lines.append(f"[RAG_CONTEXT] doc_id={payload.doc_id}")

        injected_prefix = "\n".join(injected_lines).strip()
        text = payload.user_text
        if payload.prefix:
            text = f"{payload.prefix}\n{text}"
        if injected_prefix:
            text = f"{injected_prefix}\n{text}"
        return text

    @staticmethod
    def _create_trace_recorder(payload: AgentRunIn) -> TraceRecorder:
        return TraceRecorder.create(
            trace_type="agent_run",
            name="agent.chat",
            group_id=payload.group_id or "",
            doc_id=payload.doc_id or "",
            request_id=uuid.uuid4().hex,
            metadata={
                "stream": True,
                "user_text_preview": str(payload.user_text or "")[:500],
            },
        )

    def run(self, payload: AgentRunIn) -> AgentRunOut:
        prompt = self._build_prompt(payload)
        recorder = self._create_trace_recorder(payload)
        run_invocation_id = recorder.start_invocation(
            kind="agent_run",
            name="agent.run_once",
            input_payload={
                "group_id": payload.group_id,
                "doc_id": payload.doc_id,
                "prompt_preview": prompt[:1000],
            },
        )
        with bind_trace_recorder(recorder):
            try:
                reply = run_once(prompt)
                recorder.finish_invocation(
                    run_invocation_id,
                    status="completed",
                    output_payload={"reply_preview": str(reply or "")[:1000]},
                )
                recorder.close(status="completed")
                return AgentRunOut(reply=str(reply))
            except Exception as exc:
                recorder.finish_invocation(
                    run_invocation_id,
                    status="failed",
                    error={"error_type": type(exc).__name__, "message": str(exc)},
                )
                recorder.close(status="failed")
                raise

    def stream(self, payload: AgentRunIn) -> Iterator[str]:
        def send(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        recorder = self._create_trace_recorder(payload)
        initial_event = map_agent_event_to_dto(
            {
                "type": "meta",
                "group_id": payload.group_id,
                "doc_id": payload.doc_id,
                "user_text": payload.user_text,
                "trace_id": recorder.trace_id,
                "trace_path": recorder.output_path,
                "status": "running",
            },
            trace_id=recorder.trace_id,
        )
        yield send("trace", initial_event.model_dump())

        event_queue: queue.Queue[str | None] = queue.Queue()

        def on_event(event: dict) -> None:
            dto = map_agent_event_to_dto(event, trace_id=recorder.trace_id)
            event_queue.put(send("trace", dto.model_dump()))

        def worker() -> None:
            prompt = self._build_prompt(payload)
            run_invocation_id = recorder.start_invocation(
                kind="agent_run",
                name="agent.stream_once",
                input_payload={
                    "group_id": payload.group_id,
                    "doc_id": payload.doc_id,
                    "prompt_preview": prompt[:1000],
                },
            )
            try:
                with bind_trace_recorder(recorder):
                    final_reply = stream_once(prompt, on_event)
                recorder.finish_invocation(
                    run_invocation_id,
                    status="completed",
                    output_payload={"reply_preview": str(final_reply or "")[:1000]},
                )
                recorder.close(status="completed")
                event_queue.put(
                    send(
                        "trace",
                        map_agent_event_to_dto(
                            {
                                "type": "done",
                                "reply": final_reply,
                                "trace_id": recorder.trace_id,
                                "trace_path": recorder.output_path,
                                "status": "completed",
                            },
                            trace_id=recorder.trace_id,
                        ).model_dump(),
                    )
                )
                event_queue.put(
                    send(
                        "trace",
                        map_agent_event_to_dto(
                            {
                                "type": "trace.ready",
                                "trace_id": recorder.trace_id,
                                "trace_path": recorder.output_path,
                                "status": "completed",
                            },
                            trace_id=recorder.trace_id,
                        ).model_dump(),
                    )
                )
            except Exception as exc:
                recorder.finish_invocation(
                    run_invocation_id,
                    status="failed",
                    error={"error_type": type(exc).__name__, "message": str(exc)},
                )
                recorder.close(status="failed")
                event_queue.put(
                    send(
                        "trace",
                        map_agent_event_to_dto(
                            {
                                "type": "trace.ready",
                                "trace_id": recorder.trace_id,
                                "trace_path": recorder.output_path,
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                                "status": "failed",
                            },
                            trace_id=recorder.trace_id,
                        ).model_dump(),
                    )
                )
                raise
            finally:
                event_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = event_queue.get()
            if item is None:
                break
            yield item
