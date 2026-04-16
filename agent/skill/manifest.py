from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


SUPPORTED_SKILL_TYPES = {
    "prompt-skill",
    "script-skill",
    "tool-skill",
    "workflow-skill",
    "mcp-skill",
    "hybrid-skill",
}


class PromptEntrypoint(BaseModel):
    path: str = "SKILL.md"
    format: str = "markdown"


class ScriptEntrypoint(BaseModel):
    name: str
    path: str
    runtime: Literal["python", "shell"] = "python"
    description: str = ""

    @field_validator("name", "path")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("entrypoint field cannot be empty")
        return value


class SkillEntrypoints(BaseModel):
    prompt: PromptEntrypoint | None = Field(default_factory=PromptEntrypoint)
    scripts: list[ScriptEntrypoint] = Field(default_factory=list)


class FileSystemPermissions(BaseModel):
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)
    execute: list[str] = Field(default_factory=list)


class SkillPermissions(BaseModel):
    filesystem: FileSystemPermissions = Field(default_factory=FileSystemPermissions)
    network: bool = False
    subprocess: bool = False


class SkillRuntime(BaseModel):
    python: str = ">=3.10"
    shell: bool = False
    dependencies: list[str] = Field(default_factory=list)


class SkillCompatibility(BaseModel):
    agent_frameworks: list[str] = Field(default_factory=list)
    os: list[str] = Field(default_factory=list)


class SkillManifest(BaseModel):
    manifest_version: str = "1.0"
    name: str
    version: str = "0.1.0"
    display_name: str = ""
    description: str
    author: str = ""
    license: str = ""
    homepage: str = ""
    tags: list[str] = Field(default_factory=list)
    type: str = "hybrid-skill"
    entrypoints: SkillEntrypoints = Field(default_factory=SkillEntrypoints)
    capabilities: list[str] = Field(default_factory=list)
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    runtime: SkillRuntime = Field(default_factory=SkillRuntime)
    compatibility: SkillCompatibility = Field(default_factory=SkillCompatibility)
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    examples: list[dict] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("name cannot be empty")
        return value

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("description cannot be empty")
        if len(value) > 1024:
            raise ValueError("description too long")
        return value

    @field_validator("display_name")
    @classmethod
    def _default_display_name(cls, value: str, info) -> str:
        value = str(value or "").strip()
        if value:
            return value
        data = info.data or {}
        return str(data.get("name") or "")

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        value = str(value or "").strip()
        if value not in SUPPORTED_SKILL_TYPES:
            raise ValueError(f"unsupported skill type: {value}")
        return value

    @field_validator("capabilities")
    @classmethod
    def _normalize_capabilities(cls, values: list[str]) -> list[str]:
        return sorted({str(v).strip() for v in values or [] if str(v).strip()})
