from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def info(message: str) -> None:
    print(message, file=sys.stderr)


def warn(message: str) -> None:
    print(f"警告: {message}", file=sys.stderr)


def error(message: str) -> None:
    print(f"错误: {message}", file=sys.stderr)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = ""
    if default is not None:
        suffix = f" [{default}]"
    answer = input(f"{prompt}{suffix}: ").strip()
    if not answer and default is not None:
        return default
    return answer


def checkpoint_prompt() -> str:
    return ask("是否继续下一阶段？输入 Y / n / save-and-exit", default="Y").lower()


def print_status(state: dict[str, Any], project_root: Path) -> None:
    phase = state.get("current_phase", "unknown")
    phases = state.get("phases", {})
    plan = phases.get("plan", {})
    code = phases.get("code", {})
    test = phases.get("test", {})
    if phase == "plan":
        round_text = f"{plan.get('current_round', 1)}/5"
    elif phase == "code":
        rounds = code.get("rounds", [])
        round_text = f"{len(rounds) + 1}/5"
    elif phase == "test":
        iters = test.get("iterations", [])
        round_text = f"{len(iters) + 1}/{test.get('max_iterations', 5)}"
    else:
        round_text = "-"
    print(f"Project: {project_root}", file=sys.stdout)
    print(f"Phase:   {phase} ({round_text})", file=sys.stdout)
