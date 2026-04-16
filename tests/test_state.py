from __future__ import annotations

import json
from pathlib import Path

import pytest

from take_root.config import default_take_root_config, save_config
from take_root.errors import StateError
from take_root.reset import run_reset
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


def _latest_trash_dir(project_root: Path) -> Path:
    trash_root = project_root / ".take_root" / "trash"
    snapshots = sorted(path for path in trash_root.iterdir() if path.is_dir())
    assert snapshots, f"No trash snapshots found in {trash_root}"
    return snapshots[-1]


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


def test_reconcile_state_from_disk_clears_stale_plan_rounds(tmp_path: Path) -> None:
    load_or_create_state(tmp_path)
    _write_artifact(tmp_path / ".take_root" / "plan" / "jeff_proposal.md", "draft")
    transition(
        tmp_path,
        {
            "current_phase": "code",
            "phases": {
                "plan": {
                    "status": "done",
                    "jeff_done": True,
                    "jeff_proposal_path": ".take_root/plan/jeff_proposal.md",
                    "current_round": 5,
                    "rounds": [
                        {
                            "n": 1,
                            "robin_path": ".take_root/plan/robin_r1.md",
                            "robin_status": "ongoing",
                            "jack_path": ".take_root/plan/jack_r1.md",
                            "jack_status": "ongoing",
                        }
                    ],
                    "final_plan_path": ".take_root/plan/final_plan.md",
                    "converged": True,
                }
            },
        },
    )

    result = reconcile_state_from_disk(tmp_path)

    assert result["current_phase"] == "plan"
    assert result["phases"]["plan"]["status"] == "in_progress"
    assert result["phases"]["plan"]["current_round"] == 1
    assert result["phases"]["plan"]["rounds"] == []
    assert result["phases"]["plan"]["final_plan_path"] is None
    assert result["phases"]["plan"]["converged"] is False


def test_run_reset_preserves_config_and_context_by_default(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_artifact(tmp_path / ".take_root" / "plan" / "jeff_proposal.md", "draft")
    _write_artifact(tmp_path / ".take_root" / "code" / "ruby_r1.md", "ongoing")
    (tmp_path / ".take_root" / "personas").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".take_root" / "personas" / "ruby.md").write_text("override\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# ctx\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    state = run_reset(tmp_path, force=True)
    trash_dir = _latest_trash_dir(tmp_path)

    assert (tmp_path / ".take_root" / "config.yaml").exists()
    assert (tmp_path / ".take_root" / "personas" / "ruby.md").exists()
    assert not (tmp_path / ".take_root" / "plan" / "jeff_proposal.md").exists()
    assert not (tmp_path / ".take_root" / "code" / "ruby_r1.md").exists()
    assert (trash_dir / "plan" / "jeff_proposal.md").exists()
    assert (trash_dir / "code" / "ruby_r1.md").exists()
    assert (trash_dir / "state.json").exists()
    assert state["current_phase"] == "plan"
    assert state["phases"]["init"]["done"] is True
    assert state["phases"]["plan"]["status"] == "not_started"


def test_run_reset_all_clears_config_and_context(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# ctx\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    state = run_reset(tmp_path, full=True, force=True)
    trash_dir = _latest_trash_dir(tmp_path)

    assert not (tmp_path / ".take_root" / "config.yaml").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert (trash_dir / "config.yaml").exists()
    assert (trash_dir / "state.json").exists()
    assert (trash_dir / "project_root" / "CLAUDE.md").exists()
    assert (trash_dir / "project_root" / "AGENTS.md").exists()
    assert state["current_phase"] == "plan"
    assert state["phases"]["init"]["done"] is False


def test_run_reset_to_code_preserves_plan_and_clears_later_phases(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# ctx\n", encoding="utf-8")
    _write_artifact(tmp_path / ".take_root" / "plan" / "jeff_proposal.md", "draft")
    _write_artifact(tmp_path / ".take_root" / "plan" / "robin_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "plan" / "jack_r1.md", "converged")
    (tmp_path / ".take_root" / "plan" / "final_plan.md").write_text(
        (
            "---\n"
            "artifact: final_plan\n"
            "version: 1\n"
            "project_root: x\n"
            "based_on: jeff_proposal.md\n"
            "negotiation_rounds: 1\n"
            "converged: true\n"
            "created_at: 2026-04-14T00:00:00Z\n"
            "---\n"
            "# final\n"
        ),
        encoding="utf-8",
    )
    _write_artifact(tmp_path / ".take_root" / "code" / "ruby_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "code" / "peter_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "test" / "amy_r1.md", "all_pass")

    state = run_reset(tmp_path, to_phase="code", force=True)
    trash_dir = _latest_trash_dir(tmp_path)

    assert (tmp_path / ".take_root" / "plan" / "final_plan.md").exists()
    assert not (tmp_path / ".take_root" / "code" / "ruby_r1.md").exists()
    assert not (tmp_path / ".take_root" / "test" / "amy_r1.md").exists()
    assert (trash_dir / "code" / "ruby_r1.md").exists()
    assert (trash_dir / "test" / "amy_r1.md").exists()
    assert state["current_phase"] == "code"
    assert state["phases"]["plan"]["status"] == "done"
    assert state["phases"]["code"]["status"] == "not_started"


def test_run_reset_to_test_preserves_completed_code(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_artifact(tmp_path / ".take_root" / "plan" / "jeff_proposal.md", "draft")
    _write_artifact(tmp_path / ".take_root" / "plan" / "robin_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "plan" / "jack_r1.md", "converged")
    (tmp_path / ".take_root" / "plan" / "final_plan.md").write_text(
        (
            "---\n"
            "artifact: final_plan\n"
            "version: 1\n"
            "project_root: x\n"
            "based_on: jeff_proposal.md\n"
            "negotiation_rounds: 1\n"
            "converged: true\n"
            "created_at: 2026-04-14T00:00:00Z\n"
            "---\n"
            "# final\n"
        ),
        encoding="utf-8",
    )
    _write_artifact(tmp_path / ".take_root" / "code" / "ruby_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "code" / "peter_r1.md", "converged")
    _write_artifact(tmp_path / ".take_root" / "test" / "amy_r1.md", "has_failures")
    _write_artifact(tmp_path / ".take_root" / "test" / "ruby_fix_r1.md", "done")

    state = run_reset(tmp_path, to_phase="test", force=True)
    trash_dir = _latest_trash_dir(tmp_path)

    assert (tmp_path / ".take_root" / "code" / "ruby_r1.md").exists()
    assert not (tmp_path / ".take_root" / "test" / "amy_r1.md").exists()
    assert (trash_dir / "test" / "amy_r1.md").exists()
    assert state["current_phase"] == "test"
    assert state["phases"]["code"]["status"] == "done"
    assert state["phases"]["test"]["status"] == "not_started"


def test_run_reset_to_code_requires_final_plan(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)

    with pytest.raises(StateError, match=r"final_plan\.md"):
        run_reset(tmp_path, to_phase="code", force=True)


def test_run_reset_to_test_requires_completed_code(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    (tmp_path / ".take_root" / "plan" / "final_plan.md").write_text(
        (
            "---\n"
            "artifact: final_plan\n"
            "version: 1\n"
            "project_root: x\n"
            "based_on: jeff_proposal.md\n"
            "negotiation_rounds: 1\n"
            "converged: true\n"
            "created_at: 2026-04-14T00:00:00Z\n"
            "---\n"
            "# final\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(StateError, match="code 阶段未完成"):
        run_reset(tmp_path, to_phase="test", force=True)


def test_run_reset_rejects_all_with_to(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)

    with pytest.raises(StateError, match="不能同时使用"):
        run_reset(tmp_path, full=True, to_phase="plan", force=True)
