"""Workflow reset and rollback helpers for take-root."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from take_root.errors import StateError, UserAbort
from take_root.state import (
    default_state,
    ensure_take_root_dirs,
    reconcile_state_from_disk,
    state_path,
    take_root_dir,
    utc_now_iso,
    write_state_atomic,
)
from take_root.ui import ask, info

RESET_TARGETS = ("plan", "code", "test")
PHASE_DIRS = ("plan", "code", "test", "doctor")


def _trash_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _is_linked_agents_md(project_root: Path) -> bool:
    agents_md = project_root / "AGENTS.md"
    claude_md = project_root / "CLAUDE.md"
    if not agents_md.is_symlink() or not claude_md.exists():
        return False
    try:
        return agents_md.resolve() == claude_md.resolve()
    except FileNotFoundError:
        return False


def _init_state_from_workspace(project_root: Path) -> dict[str, Any]:
    claude_md = project_root / "CLAUDE.md"
    claude_exists = claude_md.exists()
    return {
        "done": claude_exists,
        "claude_md_generated": claude_exists,
        "claude_md_last_refresh": utc_now_iso() if claude_exists else None,
        "agents_md_symlinked": _is_linked_agents_md(project_root),
    }


def _confirm_reset(full: bool, to_phase: str | None) -> None:
    if full:
        scope = "彻底清空 take-root 配置、上下文与工件"
    elif to_phase is None or to_phase == "plan":
        scope = "回退到 plan 起点并清空 workflow 工件"
    else:
        scope = f"回退到 {to_phase} 阶段起点并清空该阶段及后续工件"
    answer = ask(f"将{scope}，继续请输入 yes", default="no").lower()
    if answer != "yes":
        raise UserAbort("已取消 reset")


def _next_trash_snapshot(project_root: Path) -> Path:
    trash_root = take_root_dir(project_root) / "trash"
    snapshot = trash_root / _trash_stamp()
    suffix = 1
    while snapshot.exists():
        snapshot = trash_root / f"{_trash_stamp()}_{suffix:02d}"
        suffix += 1
    snapshot.mkdir(parents=True, exist_ok=False)
    return snapshot


def _move_to_trash(snapshot: Path, path: Path, relative_name: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    destination = snapshot / relative_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))


def _backup_paths(project_root: Path, paths: list[tuple[Path, Path]]) -> Path | None:
    existing = [(path, relative) for path, relative in paths if path.exists() or path.is_symlink()]
    if not existing:
        return None
    snapshot = _next_trash_snapshot(project_root)
    for path, relative in existing:
        _move_to_trash(snapshot, path, relative)
    return snapshot


def _validate_reset_target(project_root: Path, to_phase: str | None) -> None:
    """Validate that the requested rollback target has the required prior artifacts."""
    if to_phase is None or to_phase == "plan":
        return
    root = take_root_dir(project_root)
    if to_phase == "code":
        if not (root / "plan" / "final_plan.md").exists():
            raise StateError("无法回退到 code：缺少 .take_root/plan/final_plan.md")
        return
    state = reconcile_state_from_disk(project_root)
    if state["phases"]["code"]["status"] != "done":
        raise StateError("无法回退到 test：code 阶段未完成，建议使用 `take-root reset --to code`")


def _paths_for_phase_reset(project_root: Path, to_phase: str | None) -> list[tuple[Path, Path]]:
    root = take_root_dir(project_root)
    phase = to_phase or "plan"
    names: list[str]
    if phase == "plan":
        names = list(PHASE_DIRS)
    elif phase == "code":
        names = ["code", "test", "doctor"]
    else:
        names = ["test", "doctor"]
    paths = [(state_path(project_root), Path("state.json"))]
    paths.extend((root / name, Path(name)) for name in names)
    return paths


def _paths_for_full_reset(project_root: Path) -> list[tuple[Path, Path]]:
    root = take_root_dir(project_root)
    paths: list[tuple[Path, Path]] = []
    for path in root.iterdir() if root.exists() else []:
        if path.name == "trash":
            continue
        paths.append((path, Path(path.name)))
    claude_md = project_root / "CLAUDE.md"
    if claude_md.exists():
        paths.append((claude_md, Path("project_root") / "CLAUDE.md"))
    agents_md = project_root / "AGENTS.md"
    if agents_md.is_symlink():
        paths.append((agents_md, Path("project_root") / "AGENTS.md"))
    return paths


def _write_phase_reset_state(project_root: Path, to_phase: str | None) -> dict[str, Any]:
    ensure_take_root_dirs(project_root)
    base = default_state(project_root)
    base["phases"]["init"] = _init_state_from_workspace(project_root)
    write_state_atomic(state_path(project_root), base)
    phase = to_phase or "plan"
    if phase == "plan":
        return base
    state = reconcile_state_from_disk(project_root)
    state["current_phase"] = phase
    if phase == "code":
        state["phases"]["code"] = base["phases"]["code"]
        state["phases"]["test"] = base["phases"]["test"]
    else:
        state["phases"]["test"] = base["phases"]["test"]
    state["updated_at"] = utc_now_iso()
    write_state_atomic(state_path(project_root), state)
    return state


def _write_full_reset_state(project_root: Path) -> dict[str, Any]:
    ensure_take_root_dirs(project_root)
    state = default_state(project_root)
    write_state_atomic(state_path(project_root), state)
    return state


def run_reset(
    project_root: Path,
    *,
    full: bool = False,
    to_phase: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Backup current workflow artifacts, then reset or roll back to the requested stage."""
    if full and to_phase is not None:
        raise StateError("--all 与 --to 不能同时使用")
    if to_phase is not None and to_phase not in RESET_TARGETS:
        raise StateError(f"--to 必须是 {'|'.join(RESET_TARGETS)}")
    if not force:
        _confirm_reset(full, to_phase)

    if full:
        snapshot = _backup_paths(project_root, _paths_for_full_reset(project_root))
        state = _write_full_reset_state(project_root)
        if snapshot is not None:
            info(f"已备份到 {snapshot}")
        info("已彻底重置 take-root；需要重新 configure/init 后再运行")
        return state

    _validate_reset_target(project_root, to_phase)
    snapshot = _backup_paths(project_root, _paths_for_phase_reset(project_root, to_phase))
    state = _write_phase_reset_state(project_root, to_phase)
    if snapshot is not None:
        info(f"已备份到 {snapshot}")
    phase = to_phase or "plan"
    if phase == "plan":
        info("已回退到 plan 起点；保留 config、persona overrides 和当前上下文文件")
    else:
        info(f"已回退到 {phase} 起点；保留前置阶段产物与当前上下文文件")
    return state
