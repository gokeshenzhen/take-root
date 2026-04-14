from __future__ import annotations

from pathlib import Path
from typing import Any

from take_root.artifacts import artifact_path
from take_root.errors import ArtifactError, ConfigError
from take_root.persona import Persona, find_harness_root, load_persona
from take_root.phases import format_boot_message, validate_artifact
from take_root.runtimes.base import BaseRuntime
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import reconcile_state_from_disk, transition
from take_root.ui import ask, info


def _runtime_for(persona: Persona, project_root: Path) -> BaseRuntime:
    if persona.runtime == "claude":
        return ClaudeRuntime(persona, project_root)
    if persona.runtime == "codex":
        return CodexRuntime(persona, project_root)
    raise ConfigError(f"Unsupported runtime: {persona.runtime}")


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))


def _find_last_ruby_impl(project_root: Path) -> Path:
    code_dir = project_root / ".take_root" / "code"
    rounds = sorted(code_dir.glob("ruby_r*.md"))
    if not rounds:
        raise ConfigError("未找到 ruby_r*.md，无法进入 test 阶段")
    return rounds[-1]


def run_test(
    project_root: Path,
    max_iterations: int = 5,
    escalate: str = "auto",
) -> dict[str, Any]:
    if max_iterations < 1:
        raise ConfigError("--max-iterations 必须 >= 1")
    if escalate not in {"auto", "always", "never"}:
        raise ConfigError("--escalate 必须是 auto|always|never")

    state = reconcile_state_from_disk(project_root)
    if state["phases"]["code"]["status"] != "done":
        raise ConfigError("请先完成 code 阶段")

    harness_root = find_harness_root()
    amy = load_persona("amy", project_root, harness_root=harness_root)
    ruby = load_persona("ruby", project_root, harness_root=harness_root)
    CodexRuntime.check_available()

    final_plan = project_root / ".take_root" / "plan" / "final_plan.md"
    if not final_plan.exists():
        raise ConfigError("final_plan.md 不存在")

    test_state = state["phases"]["test"]
    iterations: list[dict[str, Any]] = list(test_state.get("iterations", []))
    vcs_mode = str(state["phases"]["code"].get("vcs_mode") or "off")
    last_ruby_impl = _find_last_ruby_impl(project_root)

    for iteration in range(len(iterations) + 1, max_iterations + 1):
        amy_path = artifact_path(project_root, "test", f"amy_r{iteration}.md")
        ruby_fix_path = artifact_path(project_root, "test", f"ruby_fix_r{iteration}.md")

        prior_amy = [
            str((project_root / ".take_root" / "test" / f"amy_r{i}.md").resolve())
            for i in range(1, iteration)
        ]
        prior_ruby_fix = [
            str((project_root / ".take_root" / "test" / f"ruby_fix_r{i}.md").resolve())
            for i in range(1, iteration)
        ]
        latest_ruby_fix = (
            str((project_root / ".take_root" / "test" / f"ruby_fix_r{iteration - 1}.md").resolve())
            if iteration > 1
            else None
        )

        if not amy_path.exists():
            info(f"[test i{iteration}] Amy 全量测试中...")
            amy_runtime = _runtime_for(amy, project_root)
            amy_boot = format_boot_message(
                "amy",
                mode="test",
                iteration=iteration,
                project_root=str(project_root.resolve()),
                final_plan=str(final_plan.resolve()),
                prior_amy=prior_amy,
                prior_ruby_fix=prior_ruby_fix,
                latest_ruby_fix=latest_ruby_fix,
                last_ruby_impl=str(last_ruby_impl.resolve()),
                output_path=str(amy_path.resolve()),
                max_iterations=max_iterations,
                vcs_mode=vcs_mode,
            )
            amy_runtime.call_noninteractive(amy_boot, cwd=project_root, timeout_sec=3600)
        amy_meta = validate_artifact(
            amy_path,
            [
                "artifact",
                "iteration",
                "status",
                "test_command",
                "tested_commit",
                "counts",
                "duration_sec",
                "created_at",
            ],
        )
        item: dict[str, Any] = {
            "n": iteration,
            "amy_path": _relative(amy_path, project_root),
            "amy_status": amy_meta["status"],
        }
        if amy_meta["status"] == "all_pass":
            iterations.append(item)
            return transition(
                project_root,
                {
                    "current_phase": "done",
                    "phases": {
                        "test": {
                            "status": "done",
                            "all_pass": True,
                            "max_iterations": max_iterations,
                            "iterations": iterations,
                        }
                    },
                },
            )

        if not ruby_fix_path.exists():
            info(f"[test i{iteration}] Ruby 修复中...")
            ruby_runtime = _runtime_for(ruby, project_root)
            ruby_boot = format_boot_message(
                "ruby",
                mode="fix",
                iteration=iteration,
                project_root=str(project_root.resolve()),
                final_plan=str(final_plan.resolve()),
                last_ruby_impl=str(last_ruby_impl.resolve()),
                prior_ruby_fix=prior_ruby_fix,
                prior_amy=[*prior_amy, str(amy_path.resolve())],
                latest_amy=str(amy_path.resolve()),
                output_path=str(ruby_fix_path.resolve()),
                vcs_mode=vcs_mode,
                vcs_commit_prefix=f"[take-root fix r{iteration}]",
                vcs_snapshot_dir=(
                    str((project_root / ".take_root" / "code" / "snapshots").resolve())
                    if vcs_mode == "snapshot"
                    else None
                ),
            )
            ruby_runtime.call_noninteractive(ruby_boot, cwd=project_root, timeout_sec=1800)
        ruby_meta = validate_artifact(
            ruby_fix_path,
            [
                "artifact",
                "iteration",
                "addresses",
                "vcs_mode",
                "commit_sha",
                "snapshot_dir",
                "files_changed",
                "failures_addressed",
                "failures_deferred",
                "created_at",
            ],
        )
        item["ruby_fix_path"] = _relative(ruby_fix_path, project_root)
        item["failures_addressed"] = ruby_meta["failures_addressed"]
        item["failures_deferred"] = ruby_meta["failures_deferred"]
        iterations.append(item)
        state = transition(
            project_root,
            {
                "phases": {
                    "test": {
                        "status": "in_progress",
                        "max_iterations": max_iterations,
                        "iterations": iterations,
                    }
                }
            },
        )

    if escalate == "always":
        raise ArtifactError("测试迭代达到上限，仍有失败，请人工处理后重试")
    if escalate == "auto":
        choice = ask("测试迭代达到上限，是否以错误退出？输入 yes / no", default="yes").lower()
        if choice in {"yes", "y", ""}:
            raise ArtifactError("测试迭代达到上限，用户选择退出")
    return state
