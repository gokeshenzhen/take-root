from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from take_root.artifacts import artifact_path
from take_root.errors import ConfigError
from take_root.persona import Persona, find_harness_root, load_persona
from take_root.phases import format_boot_message, validate_artifact
from take_root.phases.init import run_init
from take_root.runtimes.base import BaseRuntime
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import reconcile_state_from_disk, transition
from take_root.ui import ask, info, warn

MAX_PLAN_ROUNDS = 5


def _runtime_for(persona: Persona, project_root: Path) -> BaseRuntime:
    if persona.runtime == "claude":
        return ClaudeRuntime(persona, project_root)
    if persona.runtime == "codex":
        return CodexRuntime(persona, project_root)
    raise ConfigError(f"Unsupported runtime: {persona.runtime}")


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


def run_plan(
    project_root: Path,
    reference_files: list[Path] | None = None,
    no_brainstorm: bool = False,
    max_rounds: int = MAX_PLAN_ROUNDS,
) -> dict[str, Any]:
    if max_rounds < 1 or max_rounds > MAX_PLAN_ROUNDS:
        raise ConfigError(f"--max-rounds must be 1..{MAX_PLAN_ROUNDS}")
    _maybe_refresh_claude_md(project_root)
    state = reconcile_state_from_disk(project_root)
    if not bool(state["phases"]["init"]["done"]):
        raise ConfigError("请先执行 take-root init")

    harness_root = find_harness_root()
    jeff = load_persona("jeff", project_root, harness_root=harness_root)
    robin = load_persona("robin", project_root, harness_root=harness_root)
    jack = load_persona("jack", project_root, harness_root=harness_root)
    ClaudeRuntime.check_available()

    plan_dir = project_root / ".take_root" / "plan"
    jeff_path = plan_dir / "jeff_proposal.md"
    references = reference_files or []

    if not jeff_path.exists():
        info("[plan] Jeff 交互阶段开始")
        jeff_runtime = _runtime_for(jeff, project_root)
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
    start_round = len(rounds) + 1
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
            robin_runtime = _runtime_for(robin, project_root)
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
            robin_runtime.call_noninteractive(robin_boot, cwd=project_root, timeout_sec=900)
        robin_meta = validate_artifact(
            robin_path,
            ["artifact", "round", "status", "addresses", "created_at", "remaining_concerns"],
        )

        prior_robin_plus = [*prior_robin, str(robin_path.resolve())]
        if not jack_path.exists():
            info(f"[plan r{round_num}] Jack 攻防评审中...")
            jack_runtime = _runtime_for(jack, project_root)
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
            jack_runtime.call_noninteractive(jack_boot, cwd=project_root, timeout_sec=900)
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
        robin_runtime = _runtime_for(robin, project_root)
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
        robin_runtime.call_noninteractive(finalize_boot, cwd=project_root, timeout_sec=900)
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
