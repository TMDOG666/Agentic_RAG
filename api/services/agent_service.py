from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from agent.agent.agent_with_skills import run_once, stream_once

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

    def run(self, payload: AgentRunIn) -> AgentRunOut:
        reply = run_once(self._build_prompt(payload))
        return AgentRunOut(reply=str(reply))

    def stream(self, payload: AgentRunIn) -> Iterator[str]:
        def send(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield send(
            "meta",
            {
                "group_id": payload.group_id,
                "doc_id": payload.doc_id,
                "user_text": payload.user_text,
            },
        )

        event_queue: queue.Queue[str | None] = queue.Queue()

        def on_event(event: dict) -> None:
            event_type = str(event.get("type") or "message")
            event_queue.put(send(event_type, event))

        def worker() -> None:
            try:
                final_reply = stream_once(self._build_prompt(payload), on_event)
                event_queue.put(send("done", {"reply": final_reply}))
            finally:
                event_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = event_queue.get()
            if item is None:
                break
            yield item
