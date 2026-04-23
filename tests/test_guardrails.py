from __future__ import annotations

from pathlib import Path

import pytest

from take_root.errors import PolicyError
from take_root.guardrails import snapshot_workspace


def _init_workspace(tmp_path: Path) -> Path:
    take_root = tmp_path / ".take_root"
    (take_root / "plan").mkdir(parents=True)
    (take_root / "doctor").mkdir()
    (take_root / "state.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    (take_root / "run_summary.md").write_text("---\nartifact: run_summary\n---\n", encoding="utf-8")
    output = take_root / "plan" / "robin_r1.md"
    output.write_text("# placeholder\n", encoding="utf-8")
    return output


def test_review_only_ignores_state_json(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    snapshot = snapshot_workspace(tmp_path, output)
    (tmp_path / ".take_root" / "state.json").write_text(
        '{"schema_version": 1, "updated_at": "changed"}\n', encoding="utf-8"
    )

    assert snapshot.out_of_scope_changes() == []
    snapshot.assert_only_output_changed()


def test_review_only_ignores_run_summary(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    snapshot = snapshot_workspace(tmp_path, output)
    (tmp_path / ".take_root" / "run_summary.md").write_text(
        "---\nartifact: run_summary\ngenerated_at: later\n---\n", encoding="utf-8"
    )

    assert snapshot.out_of_scope_changes() == []


def test_review_only_ignores_doctor_subtree(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    snapshot = snapshot_workspace(tmp_path, output)
    (tmp_path / ".take_root" / "doctor" / "robin_report.md").write_text(
        "# doctor\n", encoding="utf-8"
    )

    assert snapshot.out_of_scope_changes() == []


def test_review_only_still_catches_other_take_root_writes(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    snapshot = snapshot_workspace(tmp_path, output)
    (tmp_path / ".take_root" / "plan" / "sneaky.md").write_text("nope\n", encoding="utf-8")

    assert snapshot.out_of_scope_changes() == [".take_root/plan/sneaky.md"]
    with pytest.raises(PolicyError, match="review_only policy violation"):
        snapshot.assert_only_output_changed()


def test_review_only_still_catches_project_file_writes(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    snapshot = snapshot_workspace(tmp_path, output)
    (tmp_path / "src" / "main.py").write_text("x = 2\n", encoding="utf-8")

    assert snapshot.out_of_scope_changes() == ["src/main.py"]


def test_output_path_changes_are_allowed(tmp_path: Path) -> None:
    output = _init_workspace(tmp_path)
    snapshot = snapshot_workspace(tmp_path, output)
    output.write_text("# persona wrote its artifact\n", encoding="utf-8")

    assert snapshot.out_of_scope_changes() == []
