from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from take_root.errors import StateError
from take_root.frontmatter import FrontmatterError, read_frontmatter_file

LOGGER = logging.getLogger(__name__)

STATE_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def take_root_dir(project_root: Path) -> Path:
    return project_root / ".take_root"


def state_path(project_root: Path) -> Path:
    return take_root_dir(project_root) / "state.json"


def _default_init_phase() -> dict[str, Any]:
    return {
        "done": False,
        "claude_md_generated": False,
        "claude_md_last_refresh": None,
        "agents_md_symlinked": False,
    }


def _default_plan_phase() -> dict[str, Any]:
    return {
        "status": "not_started",
        "jeff_done": False,
        "jeff_proposal_path": None,
        "current_round": 1,
        "rounds": [],
        "final_plan_path": None,
        "converged": False,
    }


def _default_code_phase() -> dict[str, Any]:
    return {
        "status": "not_started",
        "vcs_mode": None,
        "vcs_initial_sha": None,
        "rounds": [],
        "converged": False,
    }


def _default_test_phase() -> dict[str, Any]:
    return {
        "status": "not_started",
        "max_iterations": 5,
        "iterations": [],
        "all_pass": False,
    }


def default_state(project_root: Path) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "project_root": str(project_root.resolve()),
        "created_at": now,
        "updated_at": now,
        "current_phase": "plan",
        "phases": {
            "init": _default_init_phase(),
            "plan": _default_plan_phase(),
            "code": _default_code_phase(),
            "test": _default_test_phase(),
        },
    }


def ensure_take_root_dirs(project_root: Path) -> None:
    root = take_root_dir(project_root)
    root.mkdir(parents=True, exist_ok=True)
    for phase in ("plan", "code", "test", "doctor"):
        (root / phase).mkdir(parents=True, exist_ok=True)
    (root / "personas").mkdir(parents=True, exist_ok=True)
    (root / "code" / "snapshots").mkdir(parents=True, exist_ok=True)


def write_state_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def load_state(project_root: Path) -> dict[str, Any]:
    path = state_path(project_root)
    if not path.exists():
        raise StateError(f"State file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StateError("state.json must be a JSON object")
    version = raw.get("schema_version")
    if version != STATE_SCHEMA_VERSION:
        raise StateError(
            f"Unsupported state schema version: {version} (expected {STATE_SCHEMA_VERSION})"
        )
    return raw


def load_or_create_state(project_root: Path) -> dict[str, Any]:
    ensure_take_root_dirs(project_root)
    path = state_path(project_root)
    if not path.exists():
        state = default_state(project_root)
        write_state_atomic(path, state)
        return state
    return load_state(project_root)


def _deep_merge_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def transition(project_root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    current = load_or_create_state(project_root)
    merged = _deep_merge_dict(current, updates)
    merged["updated_at"] = utc_now_iso()
    write_state_atomic(state_path(project_root), merged)
    return merged


def _safe_parse_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        return read_frontmatter_file(path).metadata
    except (FrontmatterError, OSError) as exc:
        LOGGER.warning("Deleting malformed artifact %s: %s", path, exc)
        try:
            path.unlink()
        except FileNotFoundError:
            return None
        return None


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(project_root.resolve()))


def _collect_numbered(prefix: str, directory: Path) -> list[tuple[int, Path]]:
    entries: list[tuple[int, Path]] = []
    for path in directory.glob(f"{prefix}*.md"):
        stem = path.stem
        suffix = stem.removeprefix(prefix)
        if suffix.isdigit():
            entries.append((int(suffix), path))
    entries.sort(key=lambda item: item[0])
    return entries


def reconcile_state_from_disk(project_root: Path) -> dict[str, Any]:
    state = load_or_create_state(project_root)
    plan_dir = take_root_dir(project_root) / "plan"
    code_dir = take_root_dir(project_root) / "code"
    test_dir = take_root_dir(project_root) / "test"
    phases = state.setdefault("phases", {})
    plan = phases.setdefault("plan", _default_plan_phase())
    code = phases.setdefault("code", _default_code_phase())
    test = phases.setdefault("test", _default_test_phase())

    jeff_path = plan_dir / "jeff_proposal.md"
    if jeff_path.exists() and _safe_parse_frontmatter(jeff_path) is not None:
        plan["jeff_done"] = True
        plan["jeff_proposal_path"] = _relative(jeff_path, project_root)
        if plan.get("status") == "not_started":
            plan["status"] = "in_progress"

    rounds_map: dict[int, dict[str, Any]] = {}
    for n, path in _collect_numbered("robin_r", plan_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = rounds_map.setdefault(n, {"n": n})
        item["robin_path"] = _relative(path, project_root)
        item["robin_status"] = parsed.get("status", "ongoing")
    for n, path in _collect_numbered("jack_r", plan_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = rounds_map.setdefault(n, {"n": n})
        item["jack_path"] = _relative(path, project_root)
        item["jack_status"] = parsed.get("status", "ongoing")
    if rounds_map:
        plan["rounds"] = [rounds_map[key] for key in sorted(rounds_map)]
        plan["current_round"] = max(rounds_map) + 1
        if plan.get("status") == "not_started":
            plan["status"] = "in_progress"

    final_plan = plan_dir / "final_plan.md"
    if final_plan.exists():
        parsed = _safe_parse_frontmatter(final_plan)
        if parsed is not None:
            plan["final_plan_path"] = _relative(final_plan, project_root)
            plan["status"] = "done"
            plan["converged"] = bool(parsed.get("converged", True))
            state["current_phase"] = "code"

    ruby_rounds: dict[int, dict[str, Any]] = {}
    for n, path in _collect_numbered("ruby_r", code_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = ruby_rounds.setdefault(n, {"n": n})
        item["ruby_path"] = _relative(path, project_root)
        item["ruby_status"] = parsed.get("status", "ongoing")
    for n, path in _collect_numbered("peter_r", code_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = ruby_rounds.setdefault(n, {"n": n})
        item["peter_path"] = _relative(path, project_root)
        item["peter_status"] = parsed.get("status", "ongoing")
    if ruby_rounds:
        code["status"] = "in_progress"
        code["rounds"] = [ruby_rounds[key] for key in sorted(ruby_rounds)]
        if all(
            item.get("ruby_status") == "converged" and item.get("peter_status") == "converged"
            for item in code["rounds"]
        ):
            code["status"] = "done"
            code["converged"] = True
            state["current_phase"] = "test"

    iterations_map: dict[int, dict[str, Any]] = {}
    for n, path in _collect_numbered("amy_r", test_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = iterations_map.setdefault(n, {"n": n})
        item["amy_path"] = _relative(path, project_root)
        item["amy_status"] = parsed.get("status", "has_failures")
    for n, path in _collect_numbered("ruby_fix_r", test_dir):
        parsed = _safe_parse_frontmatter(path)
        if parsed is None:
            continue
        item = iterations_map.setdefault(n, {"n": n})
        item["ruby_fix_path"] = _relative(path, project_root)
        item["failures_addressed"] = parsed.get("failures_addressed")
        item["failures_deferred"] = parsed.get("failures_deferred")
    if iterations_map:
        test["status"] = "in_progress"
        test["iterations"] = [iterations_map[key] for key in sorted(iterations_map)]
        latest_key = max(iterations_map)
        latest = iterations_map[latest_key]
        if latest.get("amy_status") == "all_pass":
            test["status"] = "done"
            test["all_pass"] = True
            state["current_phase"] = "done"

    state["updated_at"] = utc_now_iso()
    write_state_atomic(state_path(project_root), state)
    return state
