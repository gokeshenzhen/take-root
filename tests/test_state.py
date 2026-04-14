from __future__ import annotations

import json
from pathlib import Path

from take_root.state import (
    load_or_create_state,
    reconcile_state_from_disk,
    state_path,
    transition,
    write_state_atomic,
)


def _write_artifact(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (f"---\nartifact: demo\nstatus: {status}\ncreated_at: 2026-04-14T00:00:00Z\n---\n# 内容\n"),
        encoding="utf-8",
    )


def test_load_or_create_state_creates_skeleton(tmp_path: Path) -> None:
    state = load_or_create_state(tmp_path)
    assert state["schema_version"] == 1
    assert (tmp_path / ".take_root" / "plan").is_dir()
    assert state_path(tmp_path).exists()


def test_transition_deep_merge(tmp_path: Path) -> None:
    load_or_create_state(tmp_path)
    updated = transition(
        tmp_path,
        {
            "phases": {
                "plan": {
                    "status": "in_progress",
                    "current_round": 2,
                }
            }
        },
    )
    assert updated["phases"]["plan"]["status"] == "in_progress"
    assert updated["phases"]["plan"]["current_round"] == 2


def test_write_state_atomic_overwrites_file(tmp_path: Path) -> None:
    path = tmp_path / ".take_root" / "state.json"
    payload = {"schema_version": 1, "value": "x"}
    write_state_atomic(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["value"] == "x"
    assert not (tmp_path / ".take_root" / "state.json.tmp").exists()


def test_reconcile_state_from_disk_updates_plan(tmp_path: Path) -> None:
    load_or_create_state(tmp_path)
    _write_artifact(tmp_path / ".take_root" / "plan" / "jeff_proposal.md", "draft")
    _write_artifact(tmp_path / ".take_root" / "plan" / "robin_r1.md", "ongoing")
    _write_artifact(tmp_path / ".take_root" / "plan" / "jack_r1.md", "ongoing")
    _write_artifact(tmp_path / ".take_root" / "plan" / "final_plan.md", "done")
    result = reconcile_state_from_disk(tmp_path)
    plan = result["phases"]["plan"]
    assert plan["jeff_done"] is True
    assert plan["status"] == "done"
    assert plan["final_plan_path"] == ".take_root/plan/final_plan.md"
