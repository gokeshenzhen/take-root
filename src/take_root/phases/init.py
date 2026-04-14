from __future__ import annotations

import os
import subprocess
from pathlib import Path

from take_root.artifacts import ensure_layout
from take_root.persona import Persona
from take_root.runtimes.claude import ClaudeRuntime
from take_root.state import load_or_create_state, transition
from take_root.ui import info, warn

INIT_SYSTEM_PROMPT = (
    "You are a senior engineer doing project reconnaissance. "
    "Return only the final CLAUDE.md markdown content."
)

INIT_USER_PROMPT = (
    "Explore the project at the current working directory using read-only methods. "
    "Produce a CLAUDE.md as primary context for future AI agents. "
    "Include project purpose (1-2 lines), tech stack, top-level layout, "
    "key entrypoints, run/test/build commands, "
    "coding conventions, and non-obvious gotchas. Keep it factual and terse (200-400 lines max)."
)

REFRESH_SUFFIX = (
    " Read existing CLAUDE.md first and preserve manual sections marked by "
    "`<!-- manual: preserved across refresh -->` while updating code-derived sections. "
    "Output the full updated file."
)


def _build_init_persona() -> Persona:
    model = os.getenv("TAKE_ROOT_INIT_MODEL", "claude-opus-4-6")
    return Persona(
        name="init",
        role="bootstrap",
        runtime="claude",
        model=model,
        reasoning="medium",
        interactive=False,
        output_artifacts=["CLAUDE.md"],
        system_prompt=INIT_SYSTEM_PROMPT,
        source_path=Path("<generated>"),
        raw_frontmatter={},
    )


def _generate_claude_md(project_root: Path, refresh: bool) -> str:
    runtime = ClaudeRuntime(_build_init_persona(), project_root)
    prompt = INIT_USER_PROMPT + (REFRESH_SUFFIX if refresh else "")
    result = runtime.call_noninteractive(prompt, cwd=project_root, timeout_sec=900)
    content = result.stdout.strip()
    if not content:
        raise RuntimeError("Claude returned empty CLAUDE.md content")
    return content + "\n"


def _ensure_agents_symlink(project_root: Path) -> None:
    claude_md = project_root / "CLAUDE.md"
    agents_md = project_root / "AGENTS.md"
    if not agents_md.exists():
        agents_md.symlink_to(claude_md.name)
        info("已创建 AGENTS.md -> CLAUDE.md 软链接")
        return
    if agents_md.is_symlink():
        target = agents_md.resolve()
        if target == claude_md.resolve():
            return
    warn("AGENTS.md 已存在且不是指向 CLAUDE.md 的软链接，请手动核对并替换")


def _ensure_gitignore(project_root: Path) -> None:
    gitignore = project_root / ".gitignore"
    line = ".take_root/"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8").splitlines()
        if line in existing:
            return
        existing.append(line)
        gitignore.write_text("\n".join(existing) + "\n", encoding="utf-8")
        return
    gitignore.write_text(f"{line}\n", encoding="utf-8")


def _git_exists(project_root: Path) -> bool:
    return (project_root / ".git").exists()


def run_init(
    project_root: Path, refresh: bool = False, no_gitignore: bool = False
) -> dict[str, object]:
    ensure_layout(project_root)
    state = load_or_create_state(project_root)
    ClaudeRuntime.check_available()

    claude_md = project_root / "CLAUDE.md"
    if not claude_md.exists() or refresh:
        info("正在生成 CLAUDE.md ...")
        content = _generate_claude_md(project_root, refresh=refresh and claude_md.exists())
        claude_md.write_text(content, encoding="utf-8")
    else:
        info("已存在 CLAUDE.md，跳过生成（可用 --refresh 更新）")

    _ensure_agents_symlink(project_root)
    if _git_exists(project_root) and not no_gitignore:
        _ensure_gitignore(project_root)
    elif not _git_exists(project_root):
        info("当前项目非 Git 仓库，跳过 .gitignore 更新")

    updated = transition(
        project_root,
        {
            "current_phase": "plan",
            "phases": {
                "init": {
                    "done": True,
                    "claude_md_generated": claude_md.exists(),
                    "claude_md_last_refresh": state.get("updated_at"),
                    "agents_md_symlinked": (project_root / "AGENTS.md").is_symlink(),
                }
            },
        },
    )
    return updated


def check_git_available() -> bool:
    result = subprocess.run(
        ["git", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0
