"""Skill layer: manifest-aware SkillManager."""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from agent.skill.manifest import SkillManifest
from agent.skill.registry import SkillsRegistry


class SkillManager:
    def __init__(self, skills_dir: str = ".cursor/skills"):
        def _has_any_skill(base: Path) -> bool:
            try:
                return any((p / "skill.yaml").is_file() or (p / "SKILL.md").is_file() for p in base.iterdir() if p.is_dir())
            except Exception:
                return False

        skills_path = Path(skills_dir)
        if str(skills_dir) == ".cursor/skills":
            repo_root = Path(__file__).resolve().parents[2]
            fallback = repo_root / "agent" / ".cursor" / "skills"
            if (not skills_path.exists()) or (skills_path.exists() and not _has_any_skill(skills_path)):
                if fallback.exists() and _has_any_skill(fallback):
                    skills_path = fallback

        self.skills_dir = skills_path
        self.skills_metadata: dict[str, dict[str, Any]] = {}
        self.registry = SkillsRegistry(self.skills_dir)
        self._scan_skills()

        print("[SkillManager] 初始化完成")
        print(f"[SkillManager] Skills 目录: {self.skills_dir.absolute()}")
        print(f"[SkillManager] 发现 {len(self.skills_metadata)} 个 Skills")
        for name in self.skills_metadata.keys():
            print(f"   - {name}")

    @staticmethod
    def _safe_stat(path: Path | None) -> tuple[int, int]:
        if path is None or not path.exists() or not path.is_file():
            return 0, 0
        st = path.stat()
        return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))), int(st.st_size)

    @staticmethod
    def _parse_frontmatter(skill_file: Path) -> dict[str, Any] | None:
        try:
            content = skill_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            data = yaml.safe_load(parts[1]) or {}
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _manifest_from_frontmatter(*, skill_dir: Path, skill_file: Path, metadata: dict[str, Any]) -> SkillManifest:
        return SkillManifest.model_validate(
            {
                "manifest_version": "1.0",
                "name": metadata.get("name") or skill_dir.name,
                "version": "0.1.0",
                "display_name": metadata.get("name") or skill_dir.name,
                "description": metadata.get("description") or "",
                "type": "prompt-skill",
                "entrypoints": {
                    "prompt": {"path": skill_file.name, "format": "markdown"},
                    "scripts": [],
                },
                "capabilities": ["prompt-guidance"],
                "permissions": {
                    "filesystem": {
                        "read": [skill_file.name, "references/**", "assets/**"],
                        "write": [],
                        "execute": [],
                    },
                    "network": False,
                    "subprocess": False,
                },
                "runtime": {"python": ">=3.10", "shell": False, "dependencies": []},
            }
        )

    @staticmethod
    def _load_manifest_file(manifest_file: Path) -> dict[str, Any]:
        data = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("skill.yaml must be a mapping")
        return data

    @staticmethod
    def _normalize_entry_record(manifest: SkillManifest) -> list[dict[str, Any]]:
        return [entry.model_dump(mode="python") for entry in manifest.entrypoints.scripts]

    def _build_record(
        self,
        *,
        skill_dir: Path,
        manifest_file: Path | None,
        skill_file: Path | None,
        manifest: SkillManifest,
        source: str,
    ) -> dict[str, Any]:
        script_entries = self._normalize_entry_record(manifest)
        skill_md_mtime_ns, skill_md_size = self._safe_stat(skill_file)
        manifest_mtime_ns, manifest_size = self._safe_stat(manifest_file)
        prompt_entry = manifest.entrypoints.prompt.path if manifest.entrypoints.prompt else None

        return {
            "name": manifest.name,
            "version": manifest.version,
            "display_name": manifest.display_name or manifest.name,
            "description": manifest.description,
            "type": manifest.type,
            "source": source,
            "path": skill_dir,
            "manifest_path": str(manifest_file) if manifest_file else None,
            "manifest_file": manifest_file,
            "skill_file": skill_file,
            "prompt_entry": prompt_entry,
            "script_entries": script_entries,
            "capabilities": list(manifest.capabilities),
            "permissions": manifest.permissions.model_dump(mode="python"),
            "runtime": manifest.runtime.model_dump(mode="python"),
            "compatibility": manifest.compatibility.model_dump(mode="python"),
            "manifest": manifest.model_dump(mode="python"),
            "skill_md_mtime_ns": skill_md_mtime_ns,
            "skill_md_size": skill_md_size,
            "manifest_mtime_ns": manifest_mtime_ns,
            "manifest_size": manifest_size,
        }

    def _resolve_prompt_file(self, metadata: dict[str, Any]) -> Path | None:
        prompt_entry = metadata.get("prompt_entry")
        if not prompt_entry:
            return metadata.get("skill_file")
        return (Path(metadata["path"]) / prompt_entry).resolve()

    def _match_any(self, relative_path: str, patterns: list[str]) -> bool:
        target = PurePosixPath(relative_path.replace("\\", "/"))
        return any(fnmatch.fnmatch(str(target), pattern) for pattern in patterns)

    def _scan_skills(self) -> None:
        if not self.skills_dir.exists():
            print(f"[SkillManager] Skills 目录不存在: {self.skills_dir}")
            return

        discovered_names: set[str] = set()

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name == ".registry":
                continue

            manifest_file = skill_dir / "skill.yaml"
            skill_file = skill_dir / "SKILL.md"
            if not manifest_file.exists() and not skill_file.exists():
                continue

            skill_md_mtime_ns, skill_md_size = self._safe_stat(skill_file if skill_file.exists() else None)
            manifest_mtime_ns, manifest_size = self._safe_stat(manifest_file if manifest_file.exists() else None)

            cached = self.registry.get_skill_record_if_fresh(
                name=skill_dir.name,
                skill_md_mtime_ns=skill_md_mtime_ns,
                skill_md_size=skill_md_size,
                manifest_mtime_ns=manifest_mtime_ns,
                manifest_size=manifest_size,
            )
            if cached is not None:
                cached["path"] = skill_dir
                cached["manifest_file"] = manifest_file if manifest_file.exists() else None
                cached["skill_file"] = skill_file if skill_file.exists() else None
                self.skills_metadata[skill_dir.name] = cached
                discovered_names.add(skill_dir.name)
                continue

            try:
                if manifest_file.exists():
                    manifest = SkillManifest.model_validate(self._load_manifest_file(manifest_file))
                    source = "manifest"
                else:
                    metadata = self._parse_frontmatter(skill_file)
                    if not metadata:
                        raise ValueError("missing skill.yaml and invalid SKILL.md front matter")
                    manifest = self._manifest_from_frontmatter(skill_dir=skill_dir, skill_file=skill_file, metadata=metadata)
                    source = "frontmatter"

                if manifest.name != skill_dir.name:
                    raise ValueError(f"manifest name '{manifest.name}' must match directory name '{skill_dir.name}'")

                prompt_file = skill_dir / manifest.entrypoints.prompt.path if manifest.entrypoints.prompt else None
                if prompt_file is not None and not prompt_file.exists():
                    raise ValueError(f"prompt entry not found: {manifest.entrypoints.prompt.path}")

                for script_entry in manifest.entrypoints.scripts:
                    script_path = skill_dir / script_entry.path
                    if not script_path.exists():
                        raise ValueError(f"script entry not found: {script_entry.path}")

                record = self._build_record(
                    skill_dir=skill_dir,
                    manifest_file=manifest_file if manifest_file.exists() else None,
                    skill_file=skill_file if skill_file.exists() else None,
                    manifest=manifest,
                    source=source,
                )
                self.skills_metadata[record["name"]] = record
                self.registry.upsert_skill(record)
                discovered_names.add(record["name"])
            except Exception as exc:
                print(f"[SkillManager] 跳过无效 Skill {skill_dir.name}: {exc}")
                self.registry.delete_skill(skill_dir.name)

        self.registry.cleanup_not_in(discovered_names)

    def get_skills_prompt(self) -> str:
        if not self.skills_metadata:
            return ""
        skills_list = "\n".join(
            f"- {name}: {info['description']} [type={info.get('type')}, capabilities={','.join(info.get('capabilities', [])) or 'none'}]"
            for name, info in self.skills_metadata.items()
        )
        return (
            "\n你可以使用以下技能（Skills）：\n"
            f"{skills_list}\n\n"
            "当用户的请求与某个技能匹配时：\n"
            "1. 使用 load_skill 工具加载该技能的完整说明\n"
            "2. 遵循技能正文中的指令\n"
            "3. 如技能引用额外文件，使用 read_skill_file 加载\n"
            "4. 如技能声明了脚本入口，再使用 execute_skill_script 执行\n"
        )

    def load_skill(self, skill_name: str) -> str:
        if skill_name not in self.skills_metadata:
            available = ", ".join(sorted(self.skills_metadata.keys()))
            return f"❌ 技能 '{skill_name}' 不存在。可用技能: {available}"

        prompt_file = self._resolve_prompt_file(self.skills_metadata[skill_name])
        if prompt_file is None or not prompt_file.exists():
            return f"❌ 技能 '{skill_name}' 未声明可加载的 prompt 入口"

        try:
            content = prompt_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content
        except Exception as exc:
            return f"❌ 加载技能失败: {exc}"

    def read_skill_file(self, skill_name: str, filename: str) -> str:
        if skill_name not in self.skills_metadata:
            return f"❌ 技能 '{skill_name}' 不存在"
        if not isinstance(filename, str) or not filename.strip():
            return "❌ filename 不能为空"

        metadata = self.skills_metadata[skill_name]
        skill_dir = Path(metadata["path"]).resolve()
        requested = Path(filename)
        if requested.is_absolute() or requested.drive:
            return "❌ 不允许读取绝对路径"
        if ".." in requested.parts:
            return "❌ 不允许使用 '..' 路径"

        resolved = (skill_dir / requested).resolve()
        try:
            relative = resolved.relative_to(skill_dir).as_posix()
        except ValueError:
            return "❌ 不允许读取技能目录之外的文件"

        read_patterns = list(metadata.get("permissions", {}).get("filesystem", {}).get("read", []))
        prompt_entry = metadata.get("prompt_entry")
        if prompt_entry:
            read_patterns.append(prompt_entry)
        if not self._match_any(relative, read_patterns):
            return f"❌ 文件 '{filename}' 未在 manifest 的 read 权限中声明"
        if not resolved.exists() or not resolved.is_file():
            return f"❌ 文件 '{filename}' 在技能 '{skill_name}' 中不存在"

        try:
            return resolved.read_text(encoding="utf-8")
        except Exception as exc:
            return f"❌ 读取文件失败: {exc}"

    def execute_skill_script(self, skill_name: str, script_name: str, args: str = "") -> str:
        if skill_name not in self.skills_metadata:
            return f"❌ 技能 '{skill_name}' 不存在"

        metadata = self.skills_metadata[skill_name]
        skill_dir = Path(metadata["path"]).resolve()
        requested = Path(script_name)
        if requested.is_absolute() or requested.drive:
            return "❌ 不允许执行绝对路径脚本"
        if ".." in requested.parts:
            return "❌ 不允许使用 '..' 路径"

        declared_entries = {entry["path"]: entry for entry in metadata.get("script_entries", [])}
        relative_script = requested.as_posix()
        if relative_script not in declared_entries:
            return f"❌ 脚本 '{script_name}' 未在 manifest.entrypoints.scripts 中声明"

        execute_patterns = list(metadata.get("permissions", {}).get("filesystem", {}).get("execute", []))
        if not bool(metadata.get("permissions", {}).get("subprocess", False)):
            return f"❌ 技能 '{skill_name}' 未启用 subprocess 权限"
        if not self._match_any(relative_script, execute_patterns):
            return f"❌ 脚本 '{script_name}' 未在 manifest 的 execute 权限中声明"

        script_path = (skill_dir / requested).resolve()
        try:
            script_path.relative_to(skill_dir)
        except ValueError:
            return "❌ 不允许执行技能目录之外的脚本"

        if not script_path.exists():
            return f"❌ 脚本 '{script_name}' 不存在"

        entry = declared_entries[relative_script]
        runtime = entry.get("runtime", "python")
        if runtime == "python":
            cmd = ["python", str(script_path)]
        elif runtime == "shell":
            if not metadata.get("runtime", {}).get("shell", False):
                return f"❌ 技能 '{skill_name}' 未启用 shell runtime"
            cmd = ["bash", str(script_path)]
        else:
            return f"❌ 不支持的脚本 runtime: {runtime}"

        if args:
            cmd.extend(shlex.split(args))

        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                cwd=Path.cwd(),
                env=env,
            )
            if result.returncode == 0:
                return result.stdout
            return f"❌ 脚本执行失败:\n{result.stderr}"
        except subprocess.TimeoutExpired:
            return "❌ 脚本执行超时（30 秒）"
        except Exception as exc:
            return f"❌ 执行脚本失败: {exc}"
