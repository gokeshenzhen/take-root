from __future__ import annotations

from pathlib import Path
from typing import Any

from take_root.artifacts import artifact_path
from take_root.config import TakeRootConfig, require_config, resolve_persona_runtime_config
from take_root.errors import ArtifactError, ConfigError
from take_root.persona import Persona, find_harness_root, load_persona
from take_root.phase_ui import announce_persona_call, build_runtime_tag, render_artifact_summary
from take_root.phases import format_boot_message, validate_artifact
from take_root.runtimes.base import BaseRuntime
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import reconcile_state_from_disk, transition
from take_root.summary import write_run_summary
from take_root.ui import Spinner, ask, info


def _runtime_for(
    persona: Persona,
    project_root: Path,
    config: TakeRootConfig,
) -> BaseRuntime:
    resolved_config = resolve_persona_runtime_config(config, persona.name)
    if resolved_config.runtime_name == "claude":
        return ClaudeRuntime(persona, project_root, resolved_config=resolved_config)
    if resolved_config.runtime_name == "codex":
        return CodexRuntime(persona, project_root, resolved_config=resolved_config)
    raise ConfigError(f"Unsupported runtime: {resolved_config.runtime_name}")


def _check_runtime_available(runtime_name: str) -> None:
    if runtime_name == "claude":
        ClaudeRuntime.check_available()
        return
    if runtime_name == "codex":
        CodexRuntime.check_available()
        return
    raise ConfigError(f"Unsupported runtime: {runtime_name}")


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))


def _find_last_ruby_impl(project_root: Path) -> Path:
    code_dir = project_root / ".take_root" / "code"
    rounds = sorted(code_dir.glob("ruby_r*.md"))
    if not rounds:
        raise ConfigError("未找到 ruby_r*.md，无法进入 test 阶段")
    return rounds[-1]


def _print_test_result_summary(iteration: int, amy_meta: dict[str, Any]) -> None:
    counts = amy_meta.get("counts")
    if not isinstance(counts, dict):
        return
    info(f"[test it{iteration}] 测试结果:")
    info(f"  - status: {amy_meta['status']}")
    info(f"  - counts.passed: {counts.get('passed')}")
    info(f"  - counts.fail: {counts.get('fail')}")
    info(f"  - counts.error_test: {counts.get('error_test')}")
    info(f"  - counts.error_env: {counts.get('error_env')}")


def run_test(
    project_root: Path,
    max_iterations: int = 5,
    escalate: str = "auto",
) -> dict[str, Any]:
    if max_iterations < 1:
        raise ConfigError("--max-iterations 必须 >= 1")
    if escalate not in {"auto", "always", "never"}:
        raise ConfigError("--escalate 必须是 auto|always|never")

    config = require_config(project_root)
    state = reconcile_state_from_disk(project_root)
    code_state = state["phases"]["code"]
    if code_state["status"] != "done":
        raise ConfigError("请先完成 code 阶段")
    if not bool(code_state.get("advance_allowed")):
        next_action = code_state.get("next_action")
        if code_state.get("result") == "exhausted_stop":
            message = "code 阶段已结束，但当前结果未允许交接到 test"
            if isinstance(next_action, str) and next_action:
                message += f"；建议先执行: {next_action}"
            raise ConfigError(message)
        raise ConfigError("请先完成 code 阶段后再进入 test")

    harness_root = find_harness_root()
    amy = load_persona("amy", project_root, harness_root=harness_root)
    ruby = load_persona("ruby", project_root, harness_root=harness_root)
    for persona in (amy, ruby):
        _check_runtime_available(resolve_persona_runtime_config(config, persona.name).runtime_name)

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
        amy_elapsed_sec: float | None = None
        amy_tag = ""

        if not amy_path.exists():
            amy_resolved = resolve_persona_runtime_config(config, amy.name)
            amy_tag = build_runtime_tag(amy_resolved)
            announce_persona_call(
                phase="test",
                round_num=iteration,
                persona="amy",
                action="全量测试中",
                inputs=[
                    Path(_relative(final_plan, project_root)),
                    Path(_relative(last_ruby_impl, project_root)),
                    *[Path(_relative(Path(path), project_root)) for path in prior_amy],
                    *[Path(_relative(Path(path), project_root)) for path in prior_ruby_fix],
                ],
                output=Path(_relative(amy_path, project_root)),
                runtime_tag=amy_tag,
            )
            amy_runtime = _runtime_for(amy, project_root, config)
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
            with Spinner(f"[test it{iteration}] Amy 全量测试中") as spinner:
                amy_runtime.call_noninteractive(amy_boot, cwd=project_root, timeout_sec=3600)
            amy_elapsed_sec = spinner.elapsed_sec
        else:
            amy_elapsed_sec = None
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
        if amy_elapsed_sec is not None:
            render_artifact_summary(
                amy_path,
                persona="amy",
                elapsed_sec=amy_elapsed_sec,
                runtime_tag=amy_tag,
            )
        item: dict[str, Any] = {
            "n": iteration,
            "amy_path": _relative(amy_path, project_root),
            "amy_status": amy_meta["status"],
        }
        if amy_meta["status"] == "all_pass":
            iterations.append(item)
            state = transition(
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
            write_run_summary(project_root, state)
            _print_test_result_summary(iteration, amy_meta)
            return state

        ruby_elapsed_sec: float | None = None
        ruby_tag = ""
        if not ruby_fix_path.exists():
            ruby_resolved = resolve_persona_runtime_config(config, ruby.name)
            ruby_tag = build_runtime_tag(ruby_resolved)
            announce_persona_call(
                phase="test",
                round_num=iteration,
                persona="ruby",
                action="修复中",
                inputs=[
                    Path(_relative(final_plan, project_root)),
                    Path(_relative(last_ruby_impl, project_root)),
                    *[Path(_relative(Path(path), project_root)) for path in prior_ruby_fix],
                    *[
                        Path(_relative(Path(path), project_root))
                        for path in [*prior_amy, str(amy_path.resolve())]
                    ],
                ],
                output=Path(_relative(ruby_fix_path, project_root)),
                runtime_tag=ruby_tag,
            )
            ruby_runtime = _runtime_for(ruby, project_root, config)
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
            with Spinner(f"[test it{iteration}] Ruby 修复中") as spinner:
                ruby_runtime.call_noninteractive(ruby_boot, cwd=project_root, timeout_sec=1800)
            ruby_elapsed_sec = spinner.elapsed_sec
        else:
            ruby_elapsed_sec = None
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
        if ruby_elapsed_sec is not None:
            render_artifact_summary(
                ruby_fix_path,
                persona="ruby",
                elapsed_sec=ruby_elapsed_sec,
                runtime_tag=ruby_tag,
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
    write_run_summary(project_root, state)
    return state
