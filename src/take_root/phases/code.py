from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from take_root.artifacts import artifact_path
from take_root.config import TakeRootConfig, require_config, resolve_persona_runtime_config
from take_root.errors import ConfigError
from take_root.persona import Persona, find_harness_root, load_persona
from take_root.phase_ui import announce_persona_call, build_runtime_tag, render_artifact_summary
from take_root.phases import format_boot_message, validate_artifact
from take_root.runtimes.base import BaseRuntime, RuntimePolicy
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import reconcile_state_from_disk, transition
from take_root.summary import write_run_summary
from take_root.ui import Spinner
from take_root.vcs import VCSHandler, select_vcs_mode

DEFAULT_CODE_ROUNDS = 5
LOGGER = logging.getLogger(__name__)


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


def _normalize_files_changed(value: Any) -> list[Path]:
    if not isinstance(value, list):
        return []
    paths: list[Path] = []
    for item in value:
        if isinstance(item, str):
            paths.append(Path(item))
    return paths


def _review_range(
    vcs_mode: str, rounds: list[dict[str, Any]], current_round: dict[str, Any]
) -> dict[str, Any]:
    if vcs_mode == "git":
        prev_sha = rounds[-1].get("commit_sha") if rounds else None
        return {"prev_sha": prev_sha, "curr_sha": current_round.get("commit_sha")}
    if vcs_mode == "snapshot":
        prev_dir = rounds[-1].get("snapshot_dir") if rounds else None
        return {
            "snapshot_dirs": {
                "prev": prev_dir,
                "curr": current_round.get("snapshot_dir"),
            }
        }
    return {"prev_sha": None, "curr_sha": None, "snapshot_dirs": None}


def _resolved_vcs_metadata(
    ruby_meta: dict[str, Any], vcs_result: dict[str, str | None]
) -> dict[str, str | None]:
    commit_sha = vcs_result.get("commit_sha")
    snapshot_dir = vcs_result.get("snapshot_dir")
    if commit_sha is None:
        raw_commit_sha = ruby_meta.get("commit_sha")
        if isinstance(raw_commit_sha, str) and raw_commit_sha.strip() and raw_commit_sha != "null":
            commit_sha = raw_commit_sha
    if snapshot_dir is None:
        raw_snapshot_dir = ruby_meta.get("snapshot_dir")
        if (
            isinstance(raw_snapshot_dir, str)
            and raw_snapshot_dir.strip()
            and raw_snapshot_dir != "null"
        ):
            snapshot_dir = raw_snapshot_dir
    return {"commit_sha": commit_sha, "snapshot_dir": snapshot_dir}


def _resume_code_rounds(
    rounds: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    completed_rounds: list[dict[str, Any]] = []
    for index, item in enumerate(rounds, start=1):
        if int(item.get("n", index)) != index:
            return index, completed_rounds
        if "ruby_path" not in item:
            return index, completed_rounds
        if "peter_path" not in item:
            return index, completed_rounds
        completed_rounds.append(item)
    return len(rounds) + 1, completed_rounds


def _artifact_retry_prompt(
    *,
    boot_message: str,
    output_path: Path,
    validation_error: Exception,
) -> str:
    return (
        f"{boot_message}\n\n"
        "[take-root harness correction]\n"
        "Your previous output for "
        f"output_path={output_path} failed validation: {validation_error}\n"
        "Rewrite the artifact from scratch and write it to output_path.\n"
        "Do not modify project source files. Do not output explanations outside the artifact."
    )


def _call_noninteractive_with_artifact_retry(
    *,
    runtime: BaseRuntime,
    boot_message: str,
    cwd: Path,
    timeout_sec: int,
    output_path: Path,
    required_keys: list[str],
    max_attempts: int = 2,
) -> dict[str, Any]:
    current_boot = boot_message
    for attempt in range(1, max_attempts + 1):
        runtime.call_noninteractive(
            current_boot,
            cwd=cwd,
            timeout_sec=timeout_sec,
            policy=RuntimePolicy.review_only(output_path),
        )
        try:
            return validate_artifact(output_path, required_keys)
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            current_boot = _artifact_retry_prompt(
                boot_message=boot_message,
                output_path=output_path,
                validation_error=exc,
            )
    raise AssertionError("unreachable")


def _next_action_for_result(result: str, max_rounds: int) -> str | None:
    if result in {"converged", "exhausted_advance"}:
        return "take-root test"
    if result == "exhausted_stop":
        return f"take-root code --max-rounds {max_rounds + 1}"
    if result == "in_progress":
        return "take-root code"
    return None


def run_code(
    project_root: Path,
    plan_file: Path | None = None,
    max_rounds: int = DEFAULT_CODE_ROUNDS,
    vcs_mode: str | None = "auto",
    on_code_exhausted: Literal["stop", "advance"] = "stop",
) -> dict[str, Any]:
    if max_rounds < 1:
        raise ConfigError("--max-rounds must be >= 1")
    if on_code_exhausted not in {"stop", "advance"}:
        raise ConfigError("--on-code-exhausted 必须是 stop|advance")
    config = require_config(project_root)
    state = reconcile_state_from_disk(project_root)
    if state["phases"]["plan"]["status"] != "done":
        raise ConfigError("请先完成 plan 阶段")

    harness_root = find_harness_root()
    ruby = load_persona("ruby", project_root, harness_root=harness_root)
    peter = load_persona("peter", project_root, harness_root=harness_root)
    for persona in (ruby, peter):
        _check_runtime_available(resolve_persona_runtime_config(config, persona.name).runtime_name)

    final_plan = (
        plan_file
        if plan_file is not None
        else project_root / ".take_root" / "plan" / "final_plan.md"
    )
    if not final_plan.exists():
        raise ConfigError(f"final_plan 不存在: {final_plan}")

    phase_state = state["phases"]["code"]
    existing_rounds: list[dict[str, Any]] = list(phase_state.get("rounds", []))
    selected_mode = str(phase_state.get("vcs_mode") or vcs_mode or "auto")
    vcs_handler: VCSHandler = select_vcs_mode(project_root, selected_mode)
    mode_name = "off"
    if selected_mode in {"git", "snapshot", "off"}:
        mode_name = selected_mode
    elif vcs_handler.__class__.__name__ == "GitVCS":
        mode_name = "git"
    elif vcs_handler.__class__.__name__ == "SnapshotVCS":
        mode_name = "snapshot"

    start_round, rounds = _resume_code_rounds(existing_rounds)
    for round_num in range(start_round, max_rounds + 1):
        ruby_path = artifact_path(project_root, "code", f"ruby_r{round_num}.md")
        peter_path = artifact_path(project_root, "code", f"peter_r{round_num}.md")
        prior_ruby = [
            str((project_root / ".take_root" / "code" / f"ruby_r{i}.md").resolve())
            for i in range(1, round_num)
        ]
        prior_peter = [
            str((project_root / ".take_root" / "code" / f"peter_r{i}.md").resolve())
            for i in range(1, round_num)
        ]
        latest_peter = (
            str((project_root / ".take_root" / "code" / f"peter_r{round_num - 1}.md").resolve())
            if round_num > 1
            else None
        )
        vcs_handler.pre_round(round_num)
        ruby_elapsed_sec: float | None = None
        ruby_tag = ""

        if not ruby_path.exists():
            ruby_resolved = resolve_persona_runtime_config(config, ruby.name)
            ruby_tag = build_runtime_tag(ruby_resolved)
            announce_persona_call(
                phase="code",
                round_num=round_num,
                persona="ruby",
                action="实现中",
                inputs=[
                    Path(_relative(final_plan, project_root)),
                    *[Path(_relative(Path(path), project_root)) for path in prior_ruby],
                    *[Path(_relative(Path(path), project_root)) for path in prior_peter],
                ],
                output=Path(_relative(ruby_path, project_root)),
                runtime_tag=ruby_tag,
            )
            ruby_runtime = _runtime_for(ruby, project_root, config)
            ruby_boot = format_boot_message(
                "ruby",
                mode="implement",
                round=round_num,
                project_root=str(project_root.resolve()),
                final_plan=str(final_plan.resolve()),
                prior_ruby=prior_ruby,
                prior_peter=prior_peter,
                latest_peter=latest_peter,
                output_path=str(ruby_path.resolve()),
                vcs_mode=mode_name,
                vcs_commit_prefix=f"[take-root code r{round_num}]",
                vcs_snapshot_dir=(
                    str((project_root / ".take_root" / "code" / "snapshots").resolve())
                    if mode_name == "snapshot"
                    else None
                ),
            )
            LOGGER.debug(
                "ruby call: round=%d output_path=%s latest_peter=%s "
                "prior_ruby=%d prior_peter=%d vcs_mode=%s",
                round_num,
                ruby_path,
                latest_peter,
                len(prior_ruby),
                len(prior_peter),
                mode_name,
            )
            with Spinner(f"[code r{round_num}] Ruby 实现中") as spinner:
                ruby_runtime.call_noninteractive(ruby_boot, cwd=project_root, timeout_sec=1800)
            ruby_elapsed_sec = spinner.elapsed_sec
        else:
            ruby_elapsed_sec = None
        ruby_meta = validate_artifact(
            ruby_path,
            [
                "artifact",
                "round",
                "status",
                "addresses",
                "vcs_mode",
                "commit_sha",
                "snapshot_dir",
                "files_changed",
                "created_at",
                "open_pushbacks",
            ],
        )
        if ruby_elapsed_sec is not None:
            render_artifact_summary(
                ruby_path,
                persona="ruby",
                elapsed_sec=ruby_elapsed_sec,
                runtime_tag=ruby_tag,
            )
        files_changed = _normalize_files_changed(ruby_meta.get("files_changed"))
        vcs_result = vcs_handler.post_round(
            round_num=round_num,
            files_changed=files_changed,
            summary=f"ruby round {round_num}",
            prefix=f"[take-root code r{round_num}]",
        )
        vcs_metadata = _resolved_vcs_metadata(ruby_meta, vcs_result)
        current_round: dict[str, Any] = {
            "n": round_num,
            "ruby_path": _relative(ruby_path, project_root),
            "ruby_status": ruby_meta["status"],
            "commit_sha": vcs_metadata["commit_sha"],
            "snapshot_dir": vcs_metadata["snapshot_dir"],
        }
        peter_tag = ""

        if not peter_path.exists():
            peter_resolved = resolve_persona_runtime_config(config, peter.name)
            peter_tag = build_runtime_tag(peter_resolved)
            announce_persona_call(
                phase="code",
                round_num=round_num,
                persona="peter",
                action="评审中",
                inputs=[
                    Path(_relative(final_plan, project_root)),
                    *[Path(_relative(Path(path), project_root)) for path in prior_ruby],
                    *[Path(_relative(Path(path), project_root)) for path in prior_peter],
                    Path(_relative(ruby_path, project_root)),
                ],
                output=Path(_relative(peter_path, project_root)),
                runtime_tag=peter_tag,
            )
            peter_runtime = _runtime_for(peter, project_root, config)
            review_range = _review_range(mode_name, rounds, current_round)
            peter_boot_kwargs: dict[str, Any] = {
                "mode": "review_round",
                "round": round_num,
                "project_root": str(project_root.resolve()),
                "final_plan": str(final_plan.resolve()),
                "prior_peter": prior_peter,
                "prior_ruby": [*prior_ruby, str(ruby_path.resolve())],
                "latest_ruby": str(ruby_path.resolve()),
                "vcs_mode": mode_name,
                "output_path": str(peter_path.resolve()),
            }
            if mode_name == "snapshot":
                peter_boot_kwargs["snapshot_dirs"] = review_range["snapshot_dirs"]
            else:
                peter_boot_kwargs["review_range"] = {
                    "prev_sha": review_range.get("prev_sha"),
                    "curr_sha": review_range.get("curr_sha"),
                }
            peter_boot = format_boot_message("peter", **peter_boot_kwargs)
            LOGGER.debug(
                "peter call: round=%d output_path=%s latest_ruby=%s "
                "prior_ruby=%d prior_peter=%d vcs_mode=%s review_range=%s",
                round_num,
                peter_path,
                ruby_path,
                len(prior_ruby) + 1,
                len(prior_peter),
                mode_name,
                review_range,
            )
            with Spinner(f"[code r{round_num}] Peter 评审中") as spinner:
                peter_meta = _call_noninteractive_with_artifact_retry(
                    runtime=peter_runtime,
                    boot_message=peter_boot,
                    cwd=project_root,
                    timeout_sec=1800,
                    output_path=peter_path,
                    required_keys=[
                        "artifact",
                        "round",
                        "status",
                        "addresses",
                        "reviewed_commit",
                        "files_reviewed",
                        "open_findings",
                        "created_at",
                    ],
                )
            peter_elapsed_sec = spinner.elapsed_sec
            render_artifact_summary(
                peter_path,
                persona="peter",
                elapsed_sec=peter_elapsed_sec,
                runtime_tag=peter_tag,
            )
        else:
            peter_meta = validate_artifact(
                peter_path,
                [
                    "artifact",
                    "round",
                    "status",
                    "addresses",
                    "reviewed_commit",
                    "files_reviewed",
                    "open_findings",
                    "created_at",
                ],
            )
        current_round["peter_path"] = _relative(peter_path, project_root)
        current_round["peter_status"] = peter_meta["status"]
        rounds.append(current_round)
        state = transition(
            project_root,
            {
                "current_phase": "code",
                "phases": {
                    "code": {
                        "status": "in_progress",
                        "vcs_mode": mode_name,
                        "rounds": rounds,
                        "result": "in_progress",
                        "advance_allowed": False,
                        "next_action": _next_action_for_result("in_progress", max_rounds),
                        "last_max_rounds": max_rounds,
                    }
                },
            },
        )
        if (
            current_round["ruby_status"] == "converged"
            and current_round["peter_status"] == "converged"
        ):
            break

    converged = (
        bool(rounds)
        and rounds[-1]["ruby_status"] == "converged"
        and rounds[-1]["peter_status"] == "converged"
    )
    result = "converged"
    advance_allowed = True
    current_phase = "test"
    if not converged:
        result = "exhausted_advance" if on_code_exhausted == "advance" else "exhausted_stop"
        advance_allowed = result == "exhausted_advance"
        current_phase = "test" if advance_allowed else "code"
    state = transition(
        project_root,
        {
            "current_phase": current_phase,
            "phases": {
                "code": {
                    "status": "done",
                    "converged": converged,
                    "rounds": rounds,
                    "vcs_mode": mode_name,
                    "result": result,
                    "advance_allowed": advance_allowed,
                    "next_action": _next_action_for_result(result, max_rounds),
                    "last_max_rounds": max_rounds,
                }
            },
        },
    )
    write_run_summary(project_root, state)
    return state
