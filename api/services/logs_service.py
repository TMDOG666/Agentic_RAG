from __future__ import annotations

from collections import deque
from pathlib import Path

from grag.config import get_config_manager


class LogsService:
    def __init__(self) -> None:
        settings = get_config_manager().get_settings()
        logging_cfg = dict(getattr(settings.system, "logging", {}) or {})
        raw_path = str(logging_cfg.get("file_path", "./data/logs/grag.log") or "./data/logs/grag.log").strip()
        self._path = Path(raw_path).expanduser()
        if not self._path.is_absolute():
            self._path = (Path.cwd() / self._path).resolve()

    def tail(
        self,
        *,
        lines: int = 200,
        contains: str | None = None,
        group_id: str | None = None,
        doc_id: str | None = None,
        task_id: str | None = None,
    ) -> dict:
        limit = max(1, min(int(lines), 1000))
        filters = [
            str(contains or "").strip(),
            str(group_id or "").strip(),
            str(doc_id or "").strip(),
            str(task_id or "").strip(),
        ]
        filters = [x for x in filters if x]

        if not self._path.exists():
            return {
                "file_path": str(self._path),
                "lines": [],
                "exists": False,
            }

        matched: deque[str] = deque(maxlen=limit)
        with self._path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\r\n")
                if filters and not all(token in line for token in filters):
                    continue
                matched.append(line)

        return {
            "file_path": str(self._path),
            "lines": list(matched),
            "exists": True,
        }
