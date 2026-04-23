"""Skill layer: manifest-aware SkillManager."""

from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from agent.skill.manifest import SkillManifest
from agent.skill.registry import SkillsRegistry
from grag.observability import get_current_trace_recorder


class SkillManager:
    """技能运行时管理器。

    这一层负责：
    - 扫描与校验 manifest/frontmatter
    - 缓存技能元数据
    - 加载 skill prompt
    - 读取技能引用文件
    - 执行技能脚本

    同时这里也承担 skill runtime 内部 invocation trace 的落点，
    这样前端后续既能看到外层 tool 调用，也能看到 skill 层的真实执行链。
    """

    def __init__(self, skills_dir: str = ".cursor/skills"):
        self.skills_dir = self._resolve_skills_dir(skills_dir)
        self.skills_metadata: dict[str, dict[str, Any]] = {}
        self.registry = SkillsRegistry(self.skills_dir)
        self._scan_skills()

        print("[SkillManager] 初始化完成")
        print(f"[SkillManager] Skills 目录: {self.skills_dir.absolute()}")
        print(f"[SkillManager] 发现 {len(self.skills_metadata)} 个 Skills")
        for name in self.skills_metadata.keys():
            print(f"   - {name}")

    @staticmethod
    def _resolve_skills_dir(skills_dir: str) -> Path:
        def _has_any_skill(base: Path) -> bool:
            try:
                return any((path / "skill.yaml").is_file() or (path / "SKILL.md").is_file() for path in base.iterdir() if path.is_dir())
            except Exception:
                return False

        skills_path = Path(skills_dir)
        if str(skills_dir) != ".cursor/skills":
            return skills_path

        repo_root = Path(__file__).resolve().parents[2]
        fallback = repo_root / "agent" / ".cursor" / "skills"
        if (not skills_path.exists()) or (skills_path.exists() and not _has_any_skill(skills_path)):
            if fallback.exists() and _has_any_skill(fallback):
                return fallback
        return skills_path

    @staticmethod
    def _safe_stat(path: Path | None) -> tuple[int, int]:
        if path is None or not path.exists() or not path.is_file():
            return 0, 0
        stat = path.stat()
        return int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))), int(stat.st_size)

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

    @staticmethod
    def _resolve_prompt_file(metadata: dict[str, Any]) -> Path | None:
        prompt_entry = metadata.get("prompt_entry")
        if not prompt_entry:
            return metadata.get("skill_file")
        return (Path(metadata["path"]) / prompt_entry).resolve()

    @staticmethod
    def _match_any(relative_path: str, patterns: list[str]) -> bool:
        target = PurePosixPath(relative_path.replace("\\", "/"))
        return any(fnmatch.fnmatch(str(target), pattern) for pattern in patterns)

    @staticmethod
    def _build_error_result(message: str) -> dict[str, Any]:
        return {"ok": False, "message": str(message or "")}

    def _start_invocation(
        self,
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
        self,
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

    def _scan_skills(self) -> None:
        invocation_id = self._start_invocation(
            kind="skill_runtime",
            name="scan_skills",
            input_payload={"skills_dir": str(self.skills_dir)},
        )
        if not self.skills_dir.exists():
            print(f"[SkillManager] Skills 目录不存在: {self.skills_dir}")
            self._finish_invocation(
                invocation_id,
                status="completed",
                output_payload={"skills_count": 0, "skipped": 0},
            )
            return

        discovered_names: set[str] = set()
        skipped: list[dict[str, str]] = []

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name == ".registry":
                continue

            manifest_file = skill_dir / "skill.yaml"
            skill_file = skill_dir / "SKILL.md"
            if not manifest_file.exists() and not skill_file.exists():
                continue

            validate_invocation_id = self._start_invocation(
                kind="skill_runtime",
                name="validate_skill",
                input_payload={
                    "skill_name": skill_dir.name,
                    "manifest_exists": manifest_file.exists(),
                    "skill_md_exists": skill_file.exists(),
                },
            )

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
                self._finish_invocation(
                    validate_invocation_id,
                    status="completed",
                    output_payload={
                        "skill_name": skill_dir.name,
                        "source": cached.get("source"),
                        "cached": True,
                        "script_entries": len(cached.get("script_entries") or []),
                    },
                )
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
                self._finish_invocation(
                    validate_invocation_id,
                    status="completed",
                    output_payload={
                        "skill_name": record["name"],
                        "source": source,
                        "cached": False,
                        "type": record["type"],
                        "script_entries": len(record["script_entries"]),
                    },
                )
            except Exception as exc:
                print(f"[SkillManager] 跳过无效 Skill {skill_dir.name}: {exc}")
                self.registry.delete_skill(skill_dir.name)
                skipped.append({"skill_name": skill_dir.name, "error": str(exc)})
                self._finish_invocation(validate_invocation_id, error=exc)

        self.registry.cleanup_not_in(discovered_names)
        self._finish_invocation(
            invocation_id,
            status="completed",
            output_payload={
                "skills_count": len(self.skills_metadata),
                "skills": sorted(self.skills_metadata.keys()),
                "skipped": skipped,
            },
        )

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
            "2. 遵循技能正文中的指引\n"
            "3. 如技能引用额外文件，使用 read_skill_file 加载\n"
            "4. 如技能声明了脚本入口，再使用 execute_skill_script 执行\n"
        )

    def load_skill(self, skill_name: str) -> str:
        invocation_id = self._start_invocation(
            kind="skill_runtime",
            name="load_skill_prompt",
            input_payload={"skill_name": skill_name},
        )
        if skill_name not in self.skills_metadata:
            message = f"❌ 技能 '{skill_name}' 不存在。可用技能: {', '.join(sorted(self.skills_metadata.keys()))}"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        prompt_file = self._resolve_prompt_file(self.skills_metadata[skill_name])
        if prompt_file is None or not prompt_file.exists():
            message = f"❌ 技能 '{skill_name}' 未声明可加载的 prompt 入口"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        try:
            content = prompt_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            self._finish_invocation(
                invocation_id,
                status="completed",
                output_payload={
                    "skill_name": skill_name,
                    "prompt_file": str(prompt_file),
                    "content_chars": len(content),
                    "content_preview": content[:500],
                },
            )
            return content
        except Exception as exc:
            message = f"❌ 加载技能失败: {exc}"
            self._finish_invocation(invocation_id, error=exc)
            return message

    def read_skill_file(self, skill_name: str, filename: str) -> str:
        invocation_id = self._start_invocation(
            kind="skill_runtime",
            name="read_skill_file",
            input_payload={"skill_name": skill_name, "filename": filename},
        )
        if skill_name not in self.skills_metadata:
            message = f"❌ 技能 '{skill_name}' 不存在"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        if not isinstance(filename, str) or not filename.strip():
            message = "❌ filename 不能为空"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        metadata = self.skills_metadata[skill_name]
        skill_dir = Path(metadata["path"]).resolve()
        requested = Path(filename)
        if requested.is_absolute() or requested.drive:
            message = "❌ 不允许读取绝对路径"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        if ".." in requested.parts:
            message = "❌ 不允许使用 '..' 路径"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        resolved = (skill_dir / requested).resolve()
        try:
            relative = resolved.relative_to(skill_dir).as_posix()
        except ValueError:
            message = "❌ 不允许读取技能目录之外的文件"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        read_patterns = list(metadata.get("permissions", {}).get("filesystem", {}).get("read", []))
        prompt_entry = metadata.get("prompt_entry")
        if prompt_entry:
            read_patterns.append(prompt_entry)
        if not self._match_any(relative, read_patterns):
            message = f"❌ 文件 '{filename}' 未在 manifest 的 read 权限中声明"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        if not resolved.exists() or not resolved.is_file():
            message = f"❌ 文件 '{filename}' 在技能 '{skill_name}' 中不存在"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        try:
            content = resolved.read_text(encoding="utf-8")
            self._finish_invocation(
                invocation_id,
                status="completed",
                output_payload={
                    "skill_name": skill_name,
                    "filename": filename,
                    "resolved_path": str(resolved),
                    "content_chars": len(content),
                    "content_preview": content[:500],
                },
            )
            return content
        except Exception as exc:
            message = f"❌ 读取文件失败: {exc}"
            self._finish_invocation(invocation_id, error=exc)
            return message

    def execute_skill_script(self, skill_name: str, script_name: str, args: str = "") -> str:
        invocation_id = self._start_invocation(
            kind="skill_runtime",
            name="execute_skill_script",
            input_payload={"skill_name": skill_name, "script_name": script_name, "args": args},
        )
        if skill_name not in self.skills_metadata:
            message = f"❌ 技能 '{skill_name}' 不存在"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        metadata = self.skills_metadata[skill_name]
        skill_dir = Path(metadata["path"]).resolve()
        requested = Path(script_name)
        if requested.is_absolute() or requested.drive:
            message = "❌ 不允许执行绝对路径脚本"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        if ".." in requested.parts:
            message = "❌ 不允许使用 '..' 路径"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        declared_entries = {entry["path"]: entry for entry in metadata.get("script_entries", [])}
        relative_script = requested.as_posix()
        if relative_script not in declared_entries:
            message = f"❌ 脚本 '{script_name}' 未在 manifest.entrypoints.scripts 中声明"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        execute_patterns = list(metadata.get("permissions", {}).get("filesystem", {}).get("execute", []))
        if not bool(metadata.get("permissions", {}).get("subprocess", False)):
            message = f"❌ 技能 '{skill_name}' 未启用 subprocess 权限"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        if not self._match_any(relative_script, execute_patterns):
            message = f"❌ 脚本 '{script_name}' 未在 manifest 的 execute 权限中声明"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        script_path = (skill_dir / requested).resolve()
        try:
            script_path.relative_to(skill_dir)
        except ValueError:
            message = "❌ 不允许执行技能目录之外的脚本"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        if not script_path.exists():
            message = f"❌ 脚本 '{script_name}' 不存在"
            self._finish_invocation(invocation_id, error_message=message)
            return message

        entry = declared_entries[relative_script]
        runtime = entry.get("runtime", "python")
        if runtime == "python":
            cmd = ["python", str(script_path)]
        elif runtime == "shell":
            if not metadata.get("runtime", {}).get("shell", False):
                message = f"❌ 技能 '{skill_name}' 未启用 shell runtime"
                self._finish_invocation(invocation_id, error_message=message)
                return message
            cmd = ["bash", str(script_path)]
        else:
            message = f"❌ 不支持的脚本 runtime: {runtime}"
            self._finish_invocation(invocation_id, error_message=message)
            return message

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
                self._finish_invocation(
                    invocation_id,
                    status="completed",
                    output_payload={
                        "skill_name": skill_name,
                        "script_name": script_name,
                        "runtime": runtime,
                        "command": cmd,
                        "returncode": result.returncode,
                        "stdout_chars": len(result.stdout or ""),
                        "stderr_chars": len(result.stderr or ""),
                        "stdout_preview": (result.stdout or "")[:1000],
                    },
                )
                return result.stdout

            message = f"❌ 脚本执行失败:\n{result.stderr}"
            self._finish_invocation(
                invocation_id,
                status="failed",
                error_message=message,
                metadata={
                    "skill_name": skill_name,
                    "script_name": script_name,
                    "runtime": runtime,
                    "command": cmd,
                    "returncode": result.returncode,
                    "stderr_preview": (result.stderr or "")[:1000],
                },
            )
            return message
        except subprocess.TimeoutExpired:
            message = "❌ 脚本执行超时（30 秒）"
            self._finish_invocation(invocation_id, error_message=message)
            return message
        except Exception as exc:
            message = f"❌ 执行脚本失败: {exc}"
            self._finish_invocation(invocation_id, error=exc)
            return message
