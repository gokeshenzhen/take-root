from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from take_root.artifacts import artifact_path
from take_root.config import TakeRootConfig, require_config, resolve_persona_runtime_config
from take_root.errors import ConfigError, PolicyError
from take_root.guardrails import (
    WorkspaceSnapshot,
    scan_review_context,
    snapshot_workspace,
    write_policy_violation_report,
)
from take_root.persona import Persona, find_harness_root, load_persona
from take_root.phases import format_boot_message, validate_artifact
from take_root.phases.init import run_init
from take_root.runtimes.base import BaseRuntime, RuntimePolicy
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import reconcile_state_from_disk, transition
from take_root.ui import ask, info, warn

MAX_PLAN_ROUNDS = 5


@dataclass(frozen=True, slots=True)
class ReviewOnlyCallResult:
    snapshot: WorkspaceSnapshot
    call_error: Exception | None


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


def _is_claude_stale(project_root: Path) -> bool:
    claude_md = project_root / "CLAUDE.md"
    if not claude_md.exists():
        return True
    now = time.time()
    age_days = (now - claude_md.stat().st_mtime) / 86400
    if age_days > 7:
        return True
    git_head = project_root / ".git" / "HEAD"
    if git_head.exists() and claude_md.stat().st_mtime < git_head.stat().st_mtime:
        return True
    return False


def _maybe_refresh_claude_md(project_root: Path) -> None:
    if not _is_claude_stale(project_root):
        return
    answer = ask(
        (
            "检测到 CLAUDE.md 可能过期（超过 7 天或早于 .git/HEAD），"
            "是否先执行 init --refresh？输入 Y / n / skip"
        ),
        default="Y",
    ).lower()
    if answer in {"y", "yes", ""}:
        run_init(project_root, refresh=True)
    elif answer == "skip":
        warn("你选择跳过 CLAUDE.md 刷新")


def _round_paths(project_root: Path, round_num: int) -> tuple[Path, Path]:
    return (
        artifact_path(project_root, "plan", f"robin_r{round_num}.md"),
        artifact_path(project_root, "plan", f"jack_r{round_num}.md"),
    )


def _status_pair(round_item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(round_item.get("robin_status", "ongoing")),
        str(round_item.get("jack_status", "ongoing")),
    )


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))


def _review_context_files(
    *,
    project_root: Path,
    persona: Persona,
    proposal: Path,
    prior_robin: list[str],
    prior_jack: list[str],
    latest_peer: str | None = None,
) -> list[Path]:
    files = [
        project_root / "CLAUDE.md",
        project_root / "AGENTS.md",
        persona.source_path,
        proposal,
        *[Path(path) for path in prior_robin],
        *[Path(path) for path in prior_jack],
    ]
    if latest_peer is not None:
        files.append(Path(latest_peer))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _call_review_only_persona(
    *,
    runtime: BaseRuntime,
    persona: Persona,
    project_root: Path,
    boot_message: str,
    output_path: Path,
    context_files: list[Path],
    timeout_sec: int,
) -> ReviewOnlyCallResult:
    scan_review_context(context_files)
    snapshot = snapshot_workspace(project_root, output_path)
    call_error: Exception | None = None
    try:
        runtime.call_noninteractive(
            boot_message,
            cwd=project_root,
            timeout_sec=timeout_sec,
            policy=RuntimePolicy.review_only(output_path),
        )
    except Exception as exc:
        call_error = exc
    changed_paths = snapshot.out_of_scope_changes()
    if changed_paths:
        sample = ", ".join(changed_paths[:8])
        suffix = "" if len(changed_paths) <= 8 else f" ... (+{len(changed_paths) - 8} more)"
        policy_error = PolicyError(
            f"review_only policy violation: files outside output_path changed: {sample}{suffix}"
        )
        snapshot.restore_output_path()
        report = write_policy_violation_report(
            project_root=project_root,
            persona_name=persona.name,
            output_path=output_path,
            details=str(policy_error),
            changed_paths=changed_paths,
        )
        error = PolicyError(f"{policy_error} (evidence: {report})")
        if call_error is None:
            raise error
        raise error from call_error
    return ReviewOnlyCallResult(snapshot=snapshot, call_error=call_error)


def _finalize_review_only_artifact(
    *,
    result: ReviewOnlyCallResult,
    output_path: Path,
    validate: Callable[[], dict[str, Any]],
    persona_name: str,
) -> dict[str, Any]:
    try:
        metadata = validate()
    except Exception:
        result.snapshot.restore_output_path()
        raise
    if result.call_error is not None:
        warn(
            f"[plan] {persona_name} runtime exited with an error after producing a valid artifact; "
            f"accepting {output_path.name}: {result.call_error}"
        )
    return metadata


def _review_retry_prompt(
    *,
    boot_message: str,
    output_path: Path,
    validation_error: Exception,
    artifact_contract: str,
) -> str:
    return (
        f"{boot_message}\n\n"
        "[take-root harness correction]\n"
        f"Your previous artifact at output_path={output_path} failed validation: {validation_error}\n"
        "Rewrite the artifact from scratch and overwrite output_path.\n"
        "It must satisfy this exact required structure:\n"
        f"{artifact_contract}\n"
        "Do not write explanations outside the artifact."
    )


def _run_review_only_persona_with_validation(
    *,
    runtime: BaseRuntime,
    persona: Persona,
    project_root: Path,
    boot_message: str,
    output_path: Path,
    context_files: list[Path],
    timeout_sec: int,
    validate: Callable[[], dict[str, Any]],
    persona_name: str,
    artifact_contract: str,
    max_attempts: int = 2,
) -> dict[str, Any]:
    current_boot = boot_message
    for attempt in range(1, max_attempts + 1):
        result = _call_review_only_persona(
            runtime=runtime,
            persona=persona,
            project_root=project_root,
            boot_message=current_boot,
            output_path=output_path,
            context_files=context_files,
            timeout_sec=timeout_sec,
        )
        try:
            return _finalize_review_only_artifact(
                result=result,
                output_path=output_path,
                validate=validate,
                persona_name=persona_name,
            )
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            warn(
                f"[plan] {persona_name} produced an invalid artifact on attempt {attempt}; "
                f"retrying {output_path.name}: {exc}"
            )
            current_boot = _review_retry_prompt(
                boot_message=boot_message,
                output_path=output_path,
                validation_error=exc,
                artifact_contract=artifact_contract,
            )
    raise AssertionError("unreachable")


def _artifact_validator(path: Path, required_keys: list[str]) -> Callable[[], dict[str, Any]]:
    def _validate() -> dict[str, Any]:
        return validate_artifact(path, required_keys)

    return _validate


def _robin_artifact_contract(round_num: int) -> str:
    headings = [f"# Robin — Round {round_num} Review"]
    if round_num > 1:
        headings.append("## 1. 对 Jack 的回应")
    headings.extend(["## 2. 新发现 / 我的关切", "## 3. 收敛评估"])
    return "\n".join(headings)


def _jack_artifact_contract(round_num: int) -> str:
    headings = [f"# Jack — Round {round_num} Adversarial Review"]
    if round_num > 1:
        headings.append("## 1. 对 Robin 上轮回应的处置")
    headings.extend(["## 2. 新攻击点", "## 3. 收敛评估"])
    return "\n".join(headings)


def _final_plan_artifact_contract() -> str:
    return "\n".join(
        [
            "# 最终方案：<标题>",
            "## 1. 目标",
            "## 2. 非目标",
            "## 3. 背景与约束",
            "## 4. 设计概览",
            "## 5. 关键决策",
            "## 6. 实施步骤",
            "## 7. 验收标准",
            "## 8. 已知风险与未决问题",
        ]
    )


def _resume_round_from_state(rounds: list[dict[str, Any]]) -> int:
    for index, item in enumerate(rounds, start=1):
        if int(item.get("n", index)) != index:
            return index
        if "robin_path" not in item or "jack_path" not in item:
            return index
    return len(rounds) + 1


def run_plan(
    project_root: Path,
    reference_files: list[Path] | None = None,
    no_brainstorm: bool = False,
    max_rounds: int = MAX_PLAN_ROUNDS,
) -> dict[str, Any]:
    if max_rounds < 1 or max_rounds > MAX_PLAN_ROUNDS:
        raise ConfigError(f"--max-rounds must be 1..{MAX_PLAN_ROUNDS}")
    config = require_config(project_root)
    _maybe_refresh_claude_md(project_root)
    state = reconcile_state_from_disk(project_root)
    if not bool(state["phases"]["init"]["done"]):
        raise ConfigError("请先执行 take-root init")

    harness_root = find_harness_root()
    jeff = load_persona("jeff", project_root, harness_root=harness_root)
    robin = load_persona("robin", project_root, harness_root=harness_root)
    jack = load_persona("jack", project_root, harness_root=harness_root)
    for persona in (jeff, robin, jack):
        _check_runtime_available(resolve_persona_runtime_config(config, persona.name).runtime_name)

    plan_dir = project_root / ".take_root" / "plan"
    jeff_path = plan_dir / "jeff_proposal.md"
    references = reference_files or []

    if not jeff_path.exists():
        info("[plan] Jeff 交互阶段开始")
        jeff_runtime = _runtime_for(jeff, project_root, config)
        boot = format_boot_message(
            "jeff",
            project_root=str(project_root.resolve()),
            reference_files=[str(path.resolve()) for path in references],
            project_context={
                "claude_md": (project_root / "CLAUDE.md").exists(),
                "agents_md": (project_root / "AGENTS.md").exists(),
            },
            existing_proposal=None,
            no_brainstorm=no_brainstorm,
        )
        boot = f"{boot}\n\nPlease proceed per your workflow."
        jeff_runtime.call_interactive(boot, cwd=project_root)
        validate_artifact(
            jeff_path,
            ["artifact", "version", "status", "project_root", "references", "created_at"],
        )
        state = transition(
            project_root,
            {
                "phases": {
                    "plan": {
                        "status": "in_progress",
                        "jeff_done": True,
                        "jeff_proposal_path": _relative(jeff_path, project_root),
                    }
                }
            },
        )
    else:
        validate_artifact(jeff_path, ["artifact"])

    rounds: list[dict[str, Any]] = list(state["phases"]["plan"].get("rounds", []))
    start_round = _resume_round_from_state(rounds)
    converged = False
    for round_num in range(start_round, max_rounds + 1):
        robin_path, jack_path = _round_paths(project_root, round_num)
        prior_robin = [str((plan_dir / f"robin_r{i}.md").resolve()) for i in range(1, round_num)]
        prior_jack = [str((plan_dir / f"jack_r{i}.md").resolve()) for i in range(1, round_num)]
        latest_jack = (
            str((plan_dir / f"jack_r{round_num - 1}.md").resolve()) if round_num > 1 else None
        )
        if not robin_path.exists():
            info(f"[plan r{round_num}] Robin 评审中...")
            robin_runtime = _runtime_for(robin, project_root, config)
            robin_boot = format_boot_message(
                "robin",
                mode="review_round",
                round=round_num,
                project_root=str(project_root.resolve()),
                proposal=str(jeff_path.resolve()),
                prior_robin=prior_robin,
                prior_jack=prior_jack,
                latest_jack=latest_jack,
                output_path=str(robin_path.resolve()),
            )
            robin_meta = _run_review_only_persona_with_validation(
                runtime=robin_runtime,
                persona=robin,
                project_root=project_root,
                boot_message=robin_boot,
                output_path=robin_path,
                context_files=_review_context_files(
                    project_root=project_root,
                    persona=robin,
                    proposal=jeff_path,
                    prior_robin=prior_robin,
                    prior_jack=prior_jack,
                    latest_peer=latest_jack,
                ),
                timeout_sec=900,
                validate=_artifact_validator(
                    robin_path,
                    [
                        "artifact",
                        "round",
                        "status",
                        "addresses",
                        "created_at",
                        "remaining_concerns",
                    ],
                ),
                persona_name="robin",
                artifact_contract=_robin_artifact_contract(round_num),
            )
        else:
            robin_meta = validate_artifact(
                robin_path,
                ["artifact", "round", "status", "addresses", "created_at", "remaining_concerns"],
            )

        prior_robin_plus = [*prior_robin, str(robin_path.resolve())]
        if not jack_path.exists():
            info(f"[plan r{round_num}] Jack 攻防评审中...")
            jack_runtime = _runtime_for(jack, project_root, config)
            jack_boot = format_boot_message(
                "jack",
                mode="review_round",
                round=round_num,
                project_root=str(project_root.resolve()),
                proposal=str(jeff_path.resolve()),
                prior_robin=prior_robin_plus,
                prior_jack=prior_jack,
                latest_robin=str(robin_path.resolve()),
                output_path=str(jack_path.resolve()),
            )
            jack_meta = _run_review_only_persona_with_validation(
                runtime=jack_runtime,
                persona=jack,
                project_root=project_root,
                boot_message=jack_boot,
                output_path=jack_path,
                context_files=_review_context_files(
                    project_root=project_root,
                    persona=jack,
                    proposal=jeff_path,
                    prior_robin=prior_robin_plus,
                    prior_jack=prior_jack,
                    latest_peer=str(robin_path.resolve()),
                ),
                timeout_sec=900,
                validate=_artifact_validator(
                    jack_path,
                    ["artifact", "round", "status", "addresses", "created_at", "open_attacks"],
                ),
                persona_name="jack",
                artifact_contract=_jack_artifact_contract(round_num),
            )
        else:
            jack_meta = validate_artifact(
                jack_path,
                ["artifact", "round", "status", "addresses", "created_at", "open_attacks"],
            )

        round_item = {
            "n": round_num,
            "robin_path": _relative(robin_path, project_root),
            "robin_status": robin_meta["status"],
            "jack_path": _relative(jack_path, project_root),
            "jack_status": jack_meta["status"],
        }
        rounds.append(round_item)
        state = transition(
            project_root,
            {
                "phases": {
                    "plan": {
                        "status": "in_progress",
                        "current_round": round_num + 1,
                        "rounds": rounds,
                    }
                }
            },
        )
        robin_status, jack_status = _status_pair(round_item)
        if robin_status == "converged" and jack_status == "converged":
            converged = True
            break

    final_plan = plan_dir / "final_plan.md"
    if not final_plan.exists():
        info("[plan] Robin 最终方案收敛输出中...")
        robin_runtime = _runtime_for(robin, project_root, config)
        rounds_used = len(rounds)
        finalize_boot = format_boot_message(
            "robin",
            mode="finalize",
            project_root=str(project_root.resolve()),
            proposal=str(jeff_path.resolve()),
            prior_robin=[
                str((plan_dir / f"robin_r{i}.md").resolve()) for i in range(1, rounds_used + 1)
            ],
            prior_jack=[
                str((plan_dir / f"jack_r{i}.md").resolve()) for i in range(1, rounds_used + 1)
            ],
            output_path=str(final_plan.resolve()),
        )
        _run_review_only_persona_with_validation(
            runtime=robin_runtime,
            persona=robin,
            project_root=project_root,
            boot_message=finalize_boot,
            output_path=final_plan,
            context_files=_review_context_files(
                project_root=project_root,
                persona=robin,
                proposal=jeff_path,
                prior_robin=[
                    str((plan_dir / f"robin_r{i}.md").resolve()) for i in range(1, rounds_used + 1)
                ],
                prior_jack=[
                    str((plan_dir / f"jack_r{i}.md").resolve()) for i in range(1, rounds_used + 1)
                ],
            ),
            timeout_sec=900,
            validate=_artifact_validator(
                final_plan,
                [
                    "artifact",
                    "version",
                    "project_root",
                    "based_on",
                    "negotiation_rounds",
                    "converged",
                    "created_at",
                ],
            ),
            persona_name="robin",
            artifact_contract=_final_plan_artifact_contract(),
        )
    else:
        validate_artifact(
            final_plan,
            [
                "artifact",
                "version",
                "project_root",
                "based_on",
                "negotiation_rounds",
                "converged",
                "created_at",
            ],
        )
    return transition(
        project_root,
        {
            "current_phase": "code",
            "phases": {
                "plan": {
                    "status": "done",
                    "final_plan_path": _relative(final_plan, project_root),
                    "converged": converged,
                }
            },
        },
    )
