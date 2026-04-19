from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from take_root.config import ResolvedRuntimeConfig
from take_root.frontmatter import FrontmatterError, read_frontmatter_file
from take_root.ui import colorize, info, warn


def announce_persona_call(
    *,
    phase: str,
    round_num: int | None,
    persona: str,
    action: str,
    inputs: list[Path],
    output: Path,
    runtime_tag: str,
) -> None:
    prefix = _phase_prefix(phase, round_num)
    title = f"{prefix} {persona.capitalize()} {action}  ({runtime_tag})"
    info(colorize(f"╭─ {title}", "cyan"))
    info(colorize(f"│ in : {', '.join(_short_path(path) for path in inputs) or '-'}", "dim"))
    info(colorize(f"│ out: {_short_path(output)}", "dim"))
    info(colorize("╰────────────────────────────────────────────────────────", "cyan"))


def build_runtime_tag(resolved_config: ResolvedRuntimeConfig) -> str:
    """Format a compact model/effort tag for phase output."""
    return f"{resolved_config.resolved_model} · {resolved_config.effort or '-'}"


def render_artifact_summary(
    output_path: Path,
    *,
    persona: str,
    elapsed_sec: float,
    runtime_tag: str,
) -> None:
    """Read a generated artifact and render a small terminal summary."""
    try:
        parsed = read_frontmatter_file(output_path)
    except (FrontmatterError, OSError) as exc:
        warn(f"无法读取产物摘要 {output_path}: {exc}")
        return

    meta = parsed.metadata
    body = parsed.body
    artifact = str(meta.get("artifact", ""))
    if artifact == "peter_review":
        _render_peter_summary(output_path, meta, body, elapsed_sec, runtime_tag)
        return

    del persona
    line = _format_summary_line(meta, output_path.stem)
    if not line:
        line = f"{output_path.stem}  ({_format_elapsed_compact(elapsed_sec)})"
    status_color = _summary_color(meta)
    info(colorize(f"✓ {line}   ({_format_elapsed_compact(elapsed_sec)})", status_color))

    if artifact == "robin_review":
        _render_robin_or_neo_details(body, peer_label="回应 Neo", concern_label="新关切")
        return
    if artifact == "neo_review":
        _render_robin_or_neo_details(body, peer_label="回应 Robin", concern_label="新攻击")
        return
    if artifact == "lucy_implementation":
        _render_lucy_details(meta, body)
        return
    if artifact == "lucy_fix":
        _render_lucy_fix_details(meta)
        return
    if artifact == "amy_test_report":
        _render_amy_details(meta)
        return
    if artifact == "final_plan":
        _render_final_plan_details(meta)


def _extract_peer_response(body: str) -> list[tuple[str, str]]:
    """Extract numbered peer responses plus stance/disposition."""
    section = _find_section(
        body,
        (
            r"^## 1\. 对 Neo 的回应\s*$",
            r"^## 1\. 对 Robin 上轮回应的处置\s*$",
        ),
    )
    if section is None:
        return []
    matches = list(re.finditer(r"^###\s+([A-Z]\d+\.\d+)\b.*$", section, re.MULTILINE))
    items: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        block = section[start:end]
        stance_match = re.search(r"^- \*\*(?:立场|处置)\*\*:\s*(.+)$", block, re.MULTILINE)
        if stance_match is None:
            continue
        items.append((match.group(1), stance_match.group(1).strip()))
    return items


def _extract_top_concerns(body: str, max_items: int = 2) -> list[str]:
    """Extract the first few concern headings from the main findings section."""
    section = _find_section(
        body,
        (
            r"^## 2\. 新发现 / 我的关切\s*$",
            r"^## 2\. 新攻击点\s*$",
            r"^## 2\. 新发现\s*$",
            r"^## 3\. 失败详情\s*$",
        ),
    )
    if section is None:
        return []
    headings = re.findall(r"^###\s+(?:[A-Z]\d+\.\d+\s+)?(.+)$", section, re.MULTILINE)
    return [item.strip() for item in headings[:max_items]]


def _format_summary_line(meta: dict[str, Any], stem: str) -> str:
    """Build the frontmatter-first summary line for each persona."""
    status = str(meta.get("status", "-"))
    if meta.get("artifact") == "robin_review":
        return (
            f"{stem}  status={status}  concerns={_int_or_q(meta.get('remaining_concerns'))}  "
            f"addresses={meta.get('addresses', '-')}"
        )
    if meta.get("artifact") == "neo_review":
        return (
            f"{stem}  status={status}  attacks={_int_or_q(meta.get('open_attacks'))}  "
            f"addresses={meta.get('addresses', '-')}"
        )
    if meta.get("artifact") == "lucy_implementation":
        return (
            f"{stem}  status={status}  pushbacks={_int_or_q(meta.get('open_pushbacks'))}  "
            f"commit={_short_sha(meta.get('commit_sha'))}  "
            f"files={_list_count(meta.get('files_changed'))}"
        )
    if meta.get("artifact") == "amy_test_report":
        counts = meta.get("counts")
        fail = counts.get("fail") if isinstance(counts, dict) else "?"
        passed = counts.get("passed") if isinstance(counts, dict) else "?"
        return f"{stem}  status={status}  passed={passed}  fail={fail}"
    if meta.get("artifact") == "lucy_fix":
        return (
            f"{stem}  addressed={_int_or_q(meta.get('failures_addressed'))}  "
            f"deferred={_int_or_q(meta.get('failures_deferred'))}  "
            f"files={_list_count(meta.get('files_changed'))}"
        )
    if meta.get("artifact") == "final_plan":
        return (
            f"{stem}  rounds={_int_or_q(meta.get('negotiation_rounds'))}  "
            f"converged={meta.get('converged', '-')}"
        )
    return f"{stem}  status={status}"


def _find_section(body: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, body, re.MULTILINE)
        if match is None:
            continue
        next_heading = re.search(r"^##\s+", body[match.end() :], re.MULTILINE)
        end = len(body) if next_heading is None else match.end() + next_heading.start()
        return body[match.end() : end]
    return None


def _summary_color(meta: dict[str, Any]) -> Literal["cyan", "green", "yellow", "red", "dim"]:
    status = str(meta.get("status", "")).lower()
    if status in {"converged", "done", "all_pass"}:
        return "green"
    if status in {"ongoing"}:
        return "yellow"
    if status in {"has_failures", "failing", "failed"}:
        return "red"
    if meta.get("artifact") == "final_plan" and bool(meta.get("converged")):
        return "green"
    return "yellow"


def _render_robin_or_neo_details(body: str, *, peer_label: str, concern_label: str) -> None:
    responses = _extract_peer_response(body)[:3]
    if responses:
        joined = " · ".join(f"{ref} {stance}" for ref, stance in responses)
        info(colorize(f"  {peer_label}: {joined}", "dim"))
    concerns = _extract_top_concerns(body)
    if concerns:
        info(colorize(f"  {concern_label}: {' ; '.join(concerns)}", "yellow"))


def _render_lucy_details(meta: dict[str, Any], body: str) -> None:
    files = _string_list(meta.get("files_changed"))
    if files:
        info(colorize(f"  files: {', '.join(files[:4])}", "dim"))
    decisions = _extract_bullets(body, r"^## 3\. 实现决策\s*$")
    if decisions:
        info(colorize(f"  决策 : {decisions[0]}", "dim"))
    leftovers = _extract_bullets(body, r"^## 4\. 遗留工作 / 已知限制\s*$")
    if leftovers:
        info(colorize(f"  遗留 : {leftovers[0]}", "yellow"))


def _render_lucy_fix_details(meta: dict[str, Any]) -> None:
    addressed = meta.get("addresses")
    if isinstance(addressed, str) and addressed:
        info(colorize(f"  目标 : {addressed}", "dim"))
    files = _string_list(meta.get("files_changed"))
    if files:
        info(colorize(f"  files: {', '.join(files[:4])}", "dim"))


def _render_amy_details(meta: dict[str, Any]) -> None:
    test_command = meta.get("test_command")
    if isinstance(test_command, str) and test_command:
        info(colorize(f"  test : {test_command}", "dim"))
    counts = meta.get("counts")
    if isinstance(counts, dict):
        info(
            colorize(
                "  counts: "
                f"error_test={counts.get('error_test', '?')}  "
                f"error_env={counts.get('error_env', '?')}  "
                f"skipped={counts.get('skipped', '?')}",
                "dim",
            )
        )


def _render_final_plan_details(meta: dict[str, Any]) -> None:
    based_on = meta.get("based_on")
    if isinstance(based_on, str) and based_on:
        info(colorize(f"  based_on: {based_on}", "dim"))


def _render_peter_summary(
    output_path: Path,
    meta: dict[str, Any],
    body: str,
    elapsed_sec: float,
    runtime_tag: str,
) -> None:
    status = str(meta.get("status", "-"))
    open_count = _int_or_q(meta.get("open_findings"))
    header = (
        f"┌ {output_path.stem}  ({runtime_tag}) ── {status} · {open_count} open ┐"
    )
    info(colorize(header, _summary_color(meta)))
    findings = _extract_top_concerns(body, max_items=3)
    if findings:
        for item in findings:
            info(colorize(f"│ {item}", "dim"))
    else:
        info(colorize("│ 无未决 BLOCKER / MAJOR，评审收敛。", "dim"))
    footer = (
        f"└ reviewed={_short_sha(meta.get('reviewed_commit'))}  "
        f"elapsed={_format_elapsed_compact(elapsed_sec)} ┘"
    )
    info(colorize(footer, "dim"))


def _extract_bullets(body: str, heading_pattern: str, max_items: int = 1) -> list[str]:
    section = _find_section(body, (heading_pattern,))
    if section is None:
        return []
    bullets = re.findall(r"^- (.+)$", section, re.MULTILINE)
    return [item.strip() for item in bullets[:max_items]]


def _short_path(path: Path) -> str:
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _phase_prefix(phase: str, round_num: int | None) -> str:
    if round_num is None:
        return f"[{phase}]"
    round_label = f"it{round_num}" if phase == "test" else f"r{round_num}"
    return f"[{phase} {round_label}]"


def _format_elapsed_compact(elapsed_sec: float) -> str:
    return f"{round(elapsed_sec)}s"


def _int_or_q(value: Any) -> str:
    return str(value) if isinstance(value, int) else "?"


def _list_count(value: Any) -> str:
    return str(len(_string_list(value)))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _short_sha(value: Any) -> str:
    if not isinstance(value, str) or not value or value == "null":
        return "-"
    return value[:7]
