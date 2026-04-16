from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from take_root.config import (
    PERSONA_NAMES,
    masked_runtime_env_summary,
    require_config,
    resolve_persona_runtime_config,
)
from take_root.persona import find_harness_root, load_persona
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime
from take_root.state import utc_now_iso

DOCTOR_PROMPT = "Reply with exactly one line: provider-check-ok"
DOCTOR_SUMMARY_KEYS = (
    "persona",
    "runtime",
    "provider",
    "provider_kind",
    "base_url",
    "model_selector",
    "resolved_model",
    "effort",
    "token_source",
)


def _doctor_dir(project_root: Path) -> Path:
    path = project_root / ".take_root" / "doctor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _runtime_for(persona_name: str, project_root: Path) -> tuple[Any, dict[str, Any]]:
    config = require_config(project_root)
    persona = load_persona(persona_name, project_root, harness_root=find_harness_root())
    resolved = resolve_persona_runtime_config(config, persona_name)
    runtime_class = ClaudeRuntime if resolved.runtime_name == "claude" else CodexRuntime
    runtime_class.check_available()
    runtime = runtime_class(persona, project_root, resolved_config=resolved)
    summary: dict[str, Any] = {
        "persona": persona.name,
        "runtime": resolved.runtime_name,
        "provider": resolved.provider_name,
        "provider_kind": resolved.provider_kind,
        "base_url": resolved.base_url,
        "model_selector": resolved.model_selector,
        "resolved_model": resolved.resolved_model,
        "effort": resolved.effort,
        "token_source": resolved.token_source,
        "env_was_cleaned": resolved.env_was_cleaned,
        "cleared_env_vars": list(resolved.cleared_env_vars),
        "injected_env": masked_runtime_env_summary(resolved),
        "injected_env_keys": sorted(resolved.env),
    }
    return runtime, summary


def _report_markdown(summary: dict[str, Any], call_result: dict[str, Any] | None) -> str:
    lines = [
        "# take-root doctor",
        "",
        f"- created_at: {utc_now_iso()}",
    ]
    for key in DOCTOR_SUMMARY_KEYS:
        lines.append(f"- {key}: {summary.get(key)}")
    lines.append(f"- env_was_cleaned: {summary['env_was_cleaned']}")
    lines.append(f"- injected_env_keys: {', '.join(summary['injected_env_keys']) or '(none)'}")
    if call_result is None:
        lines.append("- call_status: skipped")
    else:
        lines.append(f"- call_status: {call_result['status']}")
        lines.append(f"- exit_code: {call_result['exit_code']}")
        lines.append(f"- duration_sec: {call_result['duration_sec']:.3f}")
    return "\n".join(lines) + "\n"


def _print_terminal_summary(
    summary: dict[str, Any],
    *,
    report_path: Path,
    call_result: dict[str, Any] | None,
) -> None:
    for key in DOCTOR_SUMMARY_KEYS:
        print(f"{key}: {summary.get(key)}")
    print(f"env_was_cleaned: {summary['env_was_cleaned']}")
    if call_result is None:
        print("call_status: skipped")
    else:
        print(f"call_status: {call_result['status']}")
        print(f"exit_code: {call_result['exit_code']}")
        print(f"duration_sec: {call_result['duration_sec']:.3f}")
    print(f"doctor_report: {report_path}")


def _run_doctor_one(
    project_root: Path,
    persona_name: str,
    *,
    no_call: bool = False,
) -> dict[str, Any]:
    runtime, summary = _runtime_for(persona_name, project_root)
    output_dir = _doctor_dir(project_root)
    report_path = output_dir / f"{persona_name}_report.md"
    env_path = output_dir / f"{persona_name}_runtime_env.json"
    stdout_path = output_dir / f"{persona_name}_call_stdout.txt"
    stderr_path = output_dir / f"{persona_name}_call_stderr.txt"

    call_result: dict[str, Any] | None = None
    if no_call:
        _write_text(stdout_path, "")
        _write_text(stderr_path, "")
    else:
        result = runtime.call_noninteractive(DOCTOR_PROMPT, cwd=project_root, timeout_sec=60)
        call_result = {
            "status": "success",
            "exit_code": result.exit_code,
            "duration_sec": result.duration_sec,
        }
        _write_text(stdout_path, result.stdout)
        _write_text(stderr_path, result.stderr)

    _write_text(report_path, _report_markdown(summary, call_result))
    env_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    _print_terminal_summary(summary, report_path=report_path, call_result=call_result)

    return {
        "persona": persona_name,
        "report_path": str(report_path),
        "env_path": str(env_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "call_status": "skipped" if call_result is None else str(call_result["status"]),
    }


def run_doctor(project_root: Path, persona_name: str, *, no_call: bool = False) -> dict[str, Any]:
    if persona_name != "all":
        return _run_doctor_one(project_root, persona_name, no_call=no_call)
    results: list[dict[str, Any]] = []
    for index, name in enumerate(PERSONA_NAMES):
        if index > 0:
            print()
        results.append(_run_doctor_one(project_root, name, no_call=no_call))
    success_count = sum(1 for item in results if item["call_status"] == "success")
    skipped_count = sum(1 for item in results if item["call_status"] == "skipped")
    print()
    print(f"summary: {success_count}/{len(results)} success, {skipped_count} skipped")
    return {
        "persona": "all",
        "results": results,
    }
