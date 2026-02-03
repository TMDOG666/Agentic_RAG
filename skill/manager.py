"""skill.manager
 
 Skill 层（Skill Layer）：SkillManager
 
 SkillManager 是 Agent Skills 体系的核心组件之一，负责：
 
 - 扫描 `.cursor/skills` 目录，发现每个 skill 的 `SKILL.md`
 - 解析 `SKILL.md` 头部 YAML Front Matter，提取 `name/description` 等元数据
 - 生成“技能索引提示词”，供 system prompt 注入，帮助模型选择合适的技能
 - 在模型需要时加载完整 skill 指令（去掉 front matter）
 - 读取技能目录内的额外文件（通常由 `[[filename]]` 引用触发）
 - 执行技能目录内的脚本（例如 `.py`/`.sh`），并返回 stdout/stderr
 
 注意：
 - SkillManager 不负责 LangGraph 编排，也不负责 LLM 选择；它只提供“技能资源管理”。
 - 该模块会打印一些启动信息（便于本地调试），这属于当前项目的预期行为。
 """
 
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional
 
import yaml
 
 
class SkillManager:
    """
    Agent Skills 管理器
 
    职责：
    1. 扫描 Skills 目录，提取所有 Skills 的元数据
    2. 生成包含 Skills 信息的系统提示词
    3. 按需加载完整的 Skill 内容
    4. 读取 Skill 中引用的额外文件
    5. 执行 Skill 中的脚本
    """
 
    def __init__(self, skills_dir: str = ".cursor/skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_metadata: Dict[str, dict] = {}
 
        # 初始化时扫描技能目录，建立“技能名 -> 元数据”的索引。
        self._scan_skills()
 
        print("✅ Skill Manager 初始化完成")
        print(f"📁 Skills 目录: {self.skills_dir.absolute()}")
        print(f"🎯 发现 {len(self.skills_metadata)} 个 Skills")
        for name in self.skills_metadata.keys():
            print(f"   - {name}")
 
    def _scan_skills(self):
        """扫描 skills 目录并构建元数据索引。
 
        目录结构约定：
 
        - `.cursor/skills/<skill_name>/SKILL.md`
 
        仅当存在 `SKILL.md` 且其包含 YAML front matter（并至少提供 `name`）时才会被识别。
        """
        if not self.skills_dir.exists():
            print(f"⚠️  Skills 目录不存在: {self.skills_dir}")
            print("💡 将创建目录并添加示例 Skills")
            return
 
        # 每个子目录视为一个候选 skill。
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
 
            # 约定：skill 的入口文件固定为 SKILL.md。
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
 
            # 从 front matter 解析出 metadata（name/description 等）。
            metadata = self._parse_metadata(skill_md)
            if not metadata or "name" not in metadata:
                print(f"⚠️  跳过无效的 Skill: {skill_dir.name}")
                continue
 
            self.skills_metadata[metadata["name"]] = {
                "description": metadata.get("description", ""),
                "path": skill_dir,
                "skill_file": skill_md,
            }
 
    def _parse_metadata(self, skill_file: Path) -> Optional[dict]:
        """解析 SKILL.md 中的 YAML front matter。
 
        SKILL.md 约定格式：
 
        ```
        ---
        name: xxx
        description: yyy
        ---
        (后续为正文指令)
        ```
 
        Args:
            skill_file: SKILL.md 路径。
 
        Returns:
            dict | None: 解析成功返回字典，否则返回 None。
        """
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()
 
            if not content.startswith("---"):
                return None
 
            # 只切两次，确保正文中的 '---' 不会干扰 front matter 的截取。
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
 
            return yaml.safe_load(parts[1])
 
        except Exception as e:
            print(f"❌ 解析 {skill_file} 失败: {e}")
            return None
 
    def get_skills_prompt(self) -> str:
        """生成 skills 列表提示词。
 
        该提示词会被注入到 system prompt 中，让模型知道有哪些技能可用，以及何时应使用
        `load_skill/read_skill_file/execute_skill_script` 这三个工具。
 
        Returns:
            str: 面向模型的 skills 说明文本；若没有发现 skills 则返回空串。
        """
        if not self.skills_metadata:
            return ""
 
        # 将技能元数据整理为简明列表（skill_name + description）。
        skills_list = "\n".join(
            [
                f"- {name}: {info['description']}"
                for name, info in self.skills_metadata.items()
            ]
        )
 
        return (
            "\n你可以使用以下技能（Skills）：\n"
            f"{skills_list}\n\n"
            "当用户的请求与某个技能的描述匹配时：\n"
            "1. 使用 load_skill 工具加载该技能的完整指令\n"
            "2. 仔细阅读并遵循技能中的指令\n"
            "3. 如果技能中引用了额外文件（例如 [[filename.md]]），使用 read_skill_file 工具加载它们\n"
            "4. 如果技能提供了脚本，使用 execute_skill_script 工具执行\n"
        )
 
    def load_skill(self, skill_name: str) -> str:
        """加载指定 skill 的“正文指令”。
 
        说明：
        - 如果 SKILL.md 包含 YAML front matter，会自动剥离 front matter，仅返回正文部分。
        - 若 skill 不存在，返回可用 skills 列表，便于模型自我纠错。
 
        Args:
            skill_name: skill 名称（对应 front matter 中的 `name`）。
 
        Returns:
            str: skill 的指令文本或错误信息。
        """
        if skill_name not in self.skills_metadata:
            available = ", ".join(self.skills_metadata.keys())
            return f"❌ 技能 '{skill_name}' 不存在。可用技能: {available}"
 
        skill_file = self.skills_metadata[skill_name]["skill_file"]
 
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()
 
            if content.startswith("---"):
                # 若存在 front matter，则剥离，只返回正文部分。
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
 
            return content
 
        except Exception as e:
            return f"❌ 加载技能失败: {e}"
 
    def read_skill_file(self, skill_name: str, filename: str) -> str:
        """读取某个 skill 目录下的额外文件内容。
 
        常见用法：当 SKILL.md 中引用了 `[[some_file.md]]` 之类的外部材料时，模型会调用
        `read_skill_file` 工具读取该文件。
 
        Args:
            skill_name: skill 名称。
            filename: 目标文件名（相对于 skill 目录）。
 
        Returns:
            str: 文件内容或错误信息。
        """
        if skill_name not in self.skills_metadata:
            return f"❌ 技能 '{skill_name}' 不存在"
 
        skill_dir = self.skills_metadata[skill_name]["path"]
        file_path = skill_dir / filename
 
        if not file_path.exists():
            return f"❌ 文件 '{filename}' 在技能 '{skill_name}' 中不存在"
 
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"❌ 读取文件失败: {e}"
 
    def execute_skill_script(self, skill_name: str, script_name: str, args: str = "") -> str:
        """执行 skill 目录内的脚本。
 
        说明：
        - 目前仅支持 `.py`（python）与 `.sh`（bash）脚本。
        - 为了兼容 Windows 终端输出，显式使用 UTF-8 解码，并启用 `errors="replace"`
          避免因异常字节导致的 UnicodeDecodeError。
        - `timeout=30` 防止模型触发长时间阻塞脚本。
 
        Args:
            skill_name: skill 名称。
            script_name: 脚本文件名。
            args: 传递给脚本的参数（以空格分隔的字符串）。
 
        Returns:
            str: stdout（成功）或包含 stderr 的错误文本（失败）。
        """
        if skill_name not in self.skills_metadata:
            return f"❌ 技能 '{skill_name}' 不存在"
 
        skill_dir = self.skills_metadata[skill_name]["path"]
        script_path = skill_dir / script_name
 
        if not script_path.exists():
            return f"❌ 脚本 '{script_name}' 在技能 '{skill_name}' 中不存在"
 
        try:
            # 根据后缀决定如何执行。
            if script_name.endswith(".py"):
                cmd = ["python", str(script_path)]
            elif script_name.endswith(".sh"):
                cmd = ["bash", str(script_path)]
            else:
                return f"❌ 不支持的脚本类型: {script_name}"

            if args:
                # args 由模型传入，约定为空格分隔；直接 split() 拼到命令行参数。
                cmd.extend(args.split())

            # 子进程环境：强制 python IO 使用 utf-8，减少 Windows 控制台编码差异。
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
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
            return "❌ 脚本执行超时（30秒）"
        except Exception as e:
            return f"❌ 执行脚本失败: {e}"
