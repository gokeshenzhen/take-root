from __future__ import annotations

from pathlib import Path
from typing import Any

from take_root.artifacts import run_summary_path
from take_root.frontmatter import serialize_frontmatter
from take_root.state import reconcile_state_from_disk, utc_now_iso


def _code_next_action(code: dict[str, Any]) -> str | None:
    next_action = code.get("next_action")
    if isinstance(next_action, str) and next_action:
        return next_action
    result = str(code.get("result", "not_started"))
    last_max_rounds = code.get("last_max_rounds")
    if result in {"converged", "exhausted_advance"}:
        return "take-root test"
    if result == "exhausted_stop":
        if isinstance(last_max_rounds, int):
            return f"take-root code --max-rounds {last_max_rounds + 1}"
        return "take-root code"
    if result == "in_progress":
        return "take-root code"
    return None


def _phase_result_labels(state: dict[str, Any]) -> dict[str, str]:
    phases = state.get("phases", {})
    plan = phases.get("plan", {})
    code = phases.get("code", {})
    test = phases.get("test", {})

    plan_label = "未开始"
    if plan.get("status") == "in_progress":
        plan_label = "进行中"
    elif plan.get("status") == "done":
        plan_label = "正常交接"

    code_result = str(code.get("result", "not_started"))
    code_label_map = {
        "not_started": "未开始",
        "in_progress": "进行中",
        "converged": "正常交接",
        "exhausted_stop": "达到预算仍未收敛，未允许交接",
        "exhausted_advance": "达到预算仍未收敛，但已带风险交接",
    }
    code_label = code_label_map.get(code_result, code_result)

    test_label = "未开始"
    if bool(test.get("all_pass")):
        test_label = "全量通过"
    elif test.get("status") == "in_progress":
        test_label = "进行中"

    return {"plan": plan_label, "code": code_label, "test": test_label}


def _unique_paths(paths: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _key_artifacts(state: dict[str, Any]) -> list[str]:
    phases = state.get("phases", {})
    plan = phases.get("plan", {})
    code = phases.get("code", {})
    test = phases.get("test", {})
    paths: list[str] = []

    final_plan_path = plan.get("final_plan_path")
    if isinstance(final_plan_path, str):
        paths.append(final_plan_path)

    code_rounds = code.get("rounds", [])
    if isinstance(code_rounds, list) and code_rounds:
        latest_code_round = code_rounds[-1]
        for key in ("lucy_path", "peter_path"):
            value = latest_code_round.get(key)
            if isinstance(value, str):
                paths.append(value)

    iterations = test.get("iterations", [])
    if isinstance(iterations, list) and iterations:
        latest_iteration = iterations[-1]
        for key in ("amy_path", "lucy_fix_path"):
            value = latest_iteration.get(key)
            if isinstance(value, str):
                paths.append(value)

    return _unique_paths(paths)


def build_summary_view(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    phases = state.get("phases", {})
    current_phase = str(state.get("current_phase", "plan"))
    code = phases.get("code", {})
    test = phases.get("test", {})
    code_result = str(code.get("result", "not_started"))
    next_action = _code_next_action(code)
    workflow_status = "ready"
    overview = "当前流程可继续执行。"
    follow_ups: list[str] = []

    if current_phase == "done" and bool(test.get("all_pass")):
        workflow_status = "done"
        overview = "当前流程已完成。原因：test 全量通过。"
        next_action = None
        follow_ups.append("当前无需额外操作。")
    elif current_phase == "plan":
        workflow_status = "ready"
        overview = "当前停在 plan。原因：尚未完成最终方案收敛。"
        next_action = "take-root plan"
        follow_ups.append("继续执行 plan，产出或更新 final_plan.md。")
    elif current_phase == "code":
        if code_result == "exhausted_stop":
            workflow_status = "blocked"
            last_max_rounds = code.get("last_max_rounds")
            budget = (
                f"max_rounds={last_max_rounds}" if isinstance(last_max_rounds, int) else "预算上限"
            )
            overview = f"当前停在 code。原因：达到 {budget} 且未收敛，未允许进入 test。"
            if next_action is not None:
                follow_ups.append(f"提高 code 预算后重跑：{next_action}")
            if isinstance(last_max_rounds, int):
                follow_ups.append(
                    "如需带风险前推，可显式执行: "
                    f"take-root code --max-rounds {last_max_rounds} --on-code-exhausted advance"
                )
        elif code_result == "in_progress":
            workflow_status = "ready"
            overview = "当前停在 code。原因：实现或评审仍在进行。"
            follow_ups.append("继续执行 code 阶段。")
        else:
            workflow_status = "ready"
            overview = "当前停在 code。原因：plan 已完成，等待或允许进入 test。"
            if next_action is not None:
                follow_ups.append(f"继续执行：{next_action}")
    elif current_phase == "test":
        if code_result == "converged":
            overview = "当前停在 test。原因：code 已正常交接，等待测试完成。"
        elif code_result == "exhausted_advance":
            overview = "当前停在 test。原因：code 达到预算但已显式带风险交接。"
        else:
            overview = "当前停在 test。原因：code 已允许进入测试。"
        workflow_status = "ready"
        next_action = "take-root test"
        follow_ups.append("继续执行 test 阶段。")

    phase_results = _phase_result_labels(state)
    return {
        "project_root": str(project_root.resolve()),
        "current_phase": current_phase,
        "workflow_status": workflow_status,
        "next_action": next_action,
        "overview": overview,
        "phase_results": phase_results,
        "key_artifacts": _key_artifacts(state),
        "follow_ups": follow_ups,
    }


def render_run_summary(view: dict[str, Any]) -> str:
    lines = [
        "# 运行摘要",
        "",
        "## 本次概览",
        view["overview"],
        "",
        "## Phase 交接结果",
        f"- plan: {view['phase_results']['plan']}",
        f"- code: {view['phase_results']['code']}",
        f"- test: {view['phase_results']['test']}",
        "",
        "## 关键产物",
    ]
    key_artifacts = view["key_artifacts"]
    if key_artifacts:
        lines.extend(f"- {path}" for path in key_artifacts)
    else:
        lines.append("- （暂无）")
    lines.extend(["", "## 后续动作"])
    follow_ups = view["follow_ups"]
    if follow_ups:
        lines.extend(f"- {item}" for item in follow_ups)
    else:
        lines.append("- 当前无需额外操作。")
    lines.append("")
    return "\n".join(lines)


def write_run_summary(project_root: Path, state: dict[str, Any] | None = None) -> Path:
    resolved_state = state if state is not None else reconcile_state_from_disk(project_root)
    view = build_summary_view(project_root, resolved_state)
    metadata = {
        "artifact": "run_summary",
        "version": 1,
        "current_phase": view["current_phase"],
        "workflow_status": view["workflow_status"],
        "next_action": view["next_action"],
        "generated_at": utc_now_iso(),
    }
    path = run_summary_path(project_root)
    path.write_text(
        serialize_frontmatter(metadata, render_run_summary(view)),
        encoding="utf-8",
    )
    return path
