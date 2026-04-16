from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class SkillsRegistry:
    """Manifest-aware SQLite registry for skill metadata cache."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.registry_dir = self.skills_dir / ".registry"
        self.db_path = self.registry_dir / "skills_registry.db"
        self.enabled = True
        self._conn: sqlite3.Connection | None = None

        if os.environ.get("SKILLS_REGISTRY_DISABLE") == "1":
            self.enabled = False
            return

        try:
            self.registry_dir.mkdir(parents=True, exist_ok=True)
            if os.environ.get("SKILLS_REGISTRY_RESET") == "1" and self.db_path.exists():
                self.db_path.unlink(missing_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        except Exception as exc:
            self.enabled = False
            self._conn = None
            print(f"[SkillsRegistry] 初始化失败，已降级为全量解析: {exc}")

    def _schema_version(self) -> str | None:
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT value FROM registry_meta WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            return str(row["value"]) if row else None
        except Exception:
            return None

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        current = self._schema_version()
        if current != SCHEMA_VERSION:
            self._rebuild_schema()
            return

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
              name TEXT PRIMARY KEY,
              version TEXT NOT NULL,
              display_name TEXT NOT NULL,
              description TEXT NOT NULL,
              skill_type TEXT NOT NULL,
              source TEXT NOT NULL,
              manifest_path TEXT,
              prompt_entry TEXT,
              capabilities_json TEXT NOT NULL,
              script_entries_json TEXT NOT NULL,
              permissions_json TEXT NOT NULL,
              runtime_json TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              skill_md_mtime_ns INTEGER NOT NULL,
              skill_md_size INTEGER NOT NULL,
              manifest_mtime_ns INTEGER NOT NULL,
              manifest_size INTEGER NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def _rebuild_schema(self) -> None:
        assert self._conn is not None
        self._conn.execute("DROP TABLE IF EXISTS skills")
        self._conn.execute("DROP TABLE IF EXISTS registry_meta")
        self._conn.execute(
            """
            CREATE TABLE registry_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE skills (
              name TEXT PRIMARY KEY,
              version TEXT NOT NULL,
              display_name TEXT NOT NULL,
              description TEXT NOT NULL,
              skill_type TEXT NOT NULL,
              source TEXT NOT NULL,
              manifest_path TEXT,
              prompt_entry TEXT,
              capabilities_json TEXT NOT NULL,
              script_entries_json TEXT NOT NULL,
              permissions_json TEXT NOT NULL,
              runtime_json TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              skill_md_mtime_ns INTEGER NOT NULL,
              skill_md_size INTEGER NOT NULL,
              manifest_mtime_ns INTEGER NOT NULL,
              manifest_size INTEGER NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "INSERT INTO registry_meta(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_skill_md_mtime ON skills(skill_md_mtime_ns)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_manifest_mtime ON skills(manifest_mtime_ns)")
        self._conn.commit()

    def get_skill_record_if_fresh(
        self,
        *,
        name: str,
        skill_md_mtime_ns: int,
        skill_md_size: int,
        manifest_mtime_ns: int,
        manifest_size: int,
    ) -> dict[str, Any] | None:
        if not self.enabled or self._conn is None:
            return None
        try:
            row = self._conn.execute(
                """
                SELECT metadata_json
                FROM skills
                WHERE name = ?
                  AND skill_md_mtime_ns = ?
                  AND skill_md_size = ?
                  AND manifest_mtime_ns = ?
                  AND manifest_size = ?
                """,
                (
                    name,
                    int(skill_md_mtime_ns),
                    int(skill_md_size),
                    int(manifest_mtime_ns),
                    int(manifest_size),
                ),
            ).fetchone()
            if row is None:
                return None
            return json.loads(str(row["metadata_json"]))
        except Exception:
            return None

    def upsert_skill(self, record: dict[str, Any]) -> None:
        if not self.enabled or self._conn is None:
            return
        try:
            self._conn.execute(
                """
                INSERT INTO skills(
                  name, version, display_name, description, skill_type, source,
                  manifest_path, prompt_entry, capabilities_json, script_entries_json,
                  permissions_json, runtime_json, metadata_json,
                  skill_md_mtime_ns, skill_md_size, manifest_mtime_ns, manifest_size, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  version = excluded.version,
                  display_name = excluded.display_name,
                  description = excluded.description,
                  skill_type = excluded.skill_type,
                  source = excluded.source,
                  manifest_path = excluded.manifest_path,
                  prompt_entry = excluded.prompt_entry,
                  capabilities_json = excluded.capabilities_json,
                  script_entries_json = excluded.script_entries_json,
                  permissions_json = excluded.permissions_json,
                  runtime_json = excluded.runtime_json,
                  metadata_json = excluded.metadata_json,
                  skill_md_mtime_ns = excluded.skill_md_mtime_ns,
                  skill_md_size = excluded.skill_md_size,
                  manifest_mtime_ns = excluded.manifest_mtime_ns,
                  manifest_size = excluded.manifest_size,
                  updated_at = excluded.updated_at
                """,
                (
                    record["name"],
                    record.get("version", "0.1.0"),
                    record.get("display_name", record["name"]),
                    record.get("description", ""),
                    record.get("type", "hybrid-skill"),
                    record.get("source", "manifest"),
                    record.get("manifest_path"),
                    record.get("prompt_entry"),
                    json.dumps(record.get("capabilities", []), ensure_ascii=False),
                    json.dumps(record.get("script_entries", []), ensure_ascii=False),
                    json.dumps(record.get("permissions", {}), ensure_ascii=False),
                    json.dumps(record.get("runtime", {}), ensure_ascii=False),
                    json.dumps(_json_safe(record), ensure_ascii=False),
                    int(record.get("skill_md_mtime_ns", 0)),
                    int(record.get("skill_md_size", 0)),
                    int(record.get("manifest_mtime_ns", 0)),
                    int(record.get("manifest_size", 0)),
                    float(time.time()),
                ),
            )
            self._conn.commit()
        except Exception:
            return

    def delete_skill(self, name: str) -> None:
        if not self.enabled or self._conn is None:
            return
        try:
            self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            self._conn.commit()
        except Exception:
            return

    def cleanup_not_in(self, names: set[str]) -> None:
        if not self.enabled or self._conn is None:
            return
        try:
            if not names:
                self._conn.execute("DELETE FROM skills")
                self._conn.commit()
                return
            placeholders = ",".join(["?"] * len(names))
            self._conn.execute(f"DELETE FROM skills WHERE name NOT IN ({placeholders})", tuple(sorted(names)))
            self._conn.commit()
        except Exception:
            return
