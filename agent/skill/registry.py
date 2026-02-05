"""skill.registry

Skill Registry（技能注册表 / 索引缓存）

本模块用于把 Skill 元数据（主要是 name/description + 变更检测信息）持久化到 SQLite，
从而避免每次启动都解析所有 `SKILL.md`。

设计原则：
1. **只缓存元数据**：不缓存 SKILL.md 正文（正文仍然按需由 SkillManager.load_skill() 读取）。
2. **可降级**：SQLite 不可用时（权限/损坏/只读），系统仍可回退到“全量解析 SKILL.md”。
3. **可扩展**：后续引入向量数据库、关键词检索、工具检索时，本类可作为“索引层入口”。

当前版本先实现持久化缓存（description + mtime/size），不做向量检索。
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional


class SkillsRegistry:
    """SQLite 版本的 Skills 元数据注册表。

    该类封装所有 SQLite 读写细节，SkillManager 只需要调用：

    - `get_description_if_fresh(...)`：若 SKILL.md 未变更，直接返回缓存 description
    - `upsert_skill(...)`：解析成功后写回缓存
    - `delete_skill(...)`：skill 无效或被删除时，从缓存移除
    - `cleanup_not_in(...)`：清理 DB 中“磁盘上已不存在”的技能

    DB 路径约定：
    - `<skills_dir>/.registry/skills_registry.db`

    注意：
    - skills_dir 默认为 `.cursor/skills`，DB 文件会跟随 skills 一起迁移。
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.registry_dir = self.skills_dir / ".registry"
        self.db_path = self.registry_dir / "skills_registry.db"

        # enabled=False 时所有方法都应“静默降级”（读返回 None，写直接忽略），
        # 以保证主流程可继续走全量解析。
        self.enabled = True
        self._conn: Optional[sqlite3.Connection] = None

        # 运维/调试开关：
        # - SKILLS_REGISTRY_DISABLE=1：完全禁用 registry（强制走全量解析）。
        # - SKILLS_REGISTRY_RESET=1：删除现有 sqlite 文件并重建（强制“全量重建缓存”）。
        if os.environ.get("SKILLS_REGISTRY_DISABLE") == "1":
            self.enabled = False
            return

        try:
            self.registry_dir.mkdir(parents=True, exist_ok=True)

            # RESET：删除 sqlite 文件，触发重建。
            # 说明：
            # - 该操作只影响缓存，不会修改任何 skill 文件。
            # - 用于排查缓存不一致、或手动切换分支导致的 registry 状态异常。
            if os.environ.get("SKILLS_REGISTRY_RESET") == "1" and self.db_path.exists():
                try:
                    self.db_path.unlink()
                except Exception:
                    # 删除失败也不阻塞：继续尝试连接现有 DB。
                    pass

            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        except Exception as e:
            self.enabled = False
            self._conn = None
            # 不抛异常：由调用方（SkillManager）继续走全量解析。
            print(f"⚠️  SkillsRegistry 初始化失败，将禁用 registry 并降级为全量解析: {e}")

    def _init_schema(self) -> None:
        """初始化 registry schema（幂等）。

        当前 schema 仅覆盖元数据缓存。

        - skills.name: skill 名称（与目录名一致）
        - skills.description: skill 描述（用于注入 prompt）
        - skills.skill_md_mtime_ns: SKILL.md 的 mtime（纳秒），用于变更检测
        - skills.skill_md_size: SKILL.md 的文件大小，用于变更检测
        - skills.updated_at: registry 更新时刻（秒）

        说明：
        - 使用 mtime_ns + size 而不是文件 hash：性能更好、足够稳定。
        - 若未来需要更强一致性，可扩展为 hash。
        """
        assert self._conn is not None

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
              name TEXT PRIMARY KEY,
              description TEXT NOT NULL,
              skill_md_mtime_ns INTEGER NOT NULL,
              skill_md_size INTEGER NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skills_mtime_ns ON skills(skill_md_mtime_ns)"
        )

        # 记录 schema version，便于未来升级。
        self._conn.execute(
            "INSERT OR IGNORE INTO registry_meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        self._conn.commit()

    def close(self) -> None:
        """显式关闭连接（可选）。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def get_description_if_fresh(self, name: str, skill_md_mtime_ns: int, skill_md_size: int) -> Optional[str]:
        """若 registry 中存在且与磁盘 SKILL.md 的 (mtime_ns, size) 一致，则返回 description。

        Args:
            name: skill 名称（目录名）
            skill_md_mtime_ns: 当前磁盘 SKILL.md mtime（纳秒）
            skill_md_size: 当前磁盘 SKILL.md 大小（字节）

        Returns:
            str | None: 命中且未变更则返回 description，否则返回 None。
        """
        if not self.enabled or self._conn is None:
            return None

        try:
            row = self._conn.execute(
                """
                SELECT description
                FROM skills
                WHERE name = ? AND skill_md_mtime_ns = ? AND skill_md_size = ?
                """,
                (name, int(skill_md_mtime_ns), int(skill_md_size)),
            ).fetchone()
            if row is None:
                return None
            desc = row["description"]
            if not isinstance(desc, str) or not desc.strip():
                return None
            return desc.strip()
        except Exception:
            # registry 异常时直接降级。
            return None

    def upsert_skill(self, name: str, description: str, skill_md_mtime_ns: int, skill_md_size: int) -> None:
        """插入或更新 skill 的缓存元数据。"""
        if not self.enabled or self._conn is None:
            return

        try:
            self._conn.execute(
                """
                INSERT INTO skills(name, description, skill_md_mtime_ns, skill_md_size, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  description = excluded.description,
                  skill_md_mtime_ns = excluded.skill_md_mtime_ns,
                  skill_md_size = excluded.skill_md_size,
                  updated_at = excluded.updated_at
                """,
                (
                    name,
                    description,
                    int(skill_md_mtime_ns),
                    int(skill_md_size),
                    float(time.time()),
                ),
            )
            self._conn.commit()
        except Exception:
            # 写失败不阻塞主流程。
            return

    def delete_skill(self, name: str) -> None:
        """从 registry 中删除一个 skill（例如该 skill 无效或被删除）。"""
        if not self.enabled or self._conn is None:
            return

        try:
            self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            self._conn.commit()
        except Exception:
            return

    def cleanup_not_in(self, names: set[str]) -> None:
        """清理 registry 中不在 `names` 集合里的 skill。

        典型用法：扫描磁盘后，把有效的 skill names 传进来，registry 自动删除“磁盘上已不存在”的条目。
        """
        if not self.enabled or self._conn is None:
            return

        try:
            if not names:
                self._conn.execute("DELETE FROM skills")
                self._conn.commit()
                return

            placeholders = ",".join(["?"] * len(names))
            self._conn.execute(
                f"DELETE FROM skills WHERE name NOT IN ({placeholders})",
                tuple(sorted(names)),
            )
            self._conn.commit()
        except Exception:
            return
