from __future__ import annotations

from pathlib import Path

from take_root.frontmatter import read_frontmatter_file
from take_root.state import load_or_create_state
from take_root.summary import build_summary_view, write_run_summary


def test_build_summary_view_for_exhausted_stop(tmp_path: Path) -> None:
    state = {
        "current_phase": "code",
        "phases": {
            "plan": {"status": "done", "final_plan_path": ".take_root/plan/final_plan.md"},
            "code": {
                "status": "done",
                "result": "exhausted_stop",
                "advance_allowed": False,
                "next_action": "take-root code --max-rounds 6",
                "last_max_rounds": 5,
                "rounds": [
                    {
                        "lucy_path": ".take_root/code/lucy_r5.md",
                        "peter_path": ".take_root/code/peter_r5.md",
                    }
                ],
            },
            "test": {"status": "not_started", "iterations": [], "all_pass": False},
        },
    }

    view = build_summary_view(tmp_path, state)

    assert view["workflow_status"] == "blocked"
    assert "达到 max_rounds=5" in view["overview"]
    assert view["next_action"] == "take-root code --max-rounds 6"
    assert view["key_artifacts"] == [
        ".take_root/plan/final_plan.md",
        ".take_root/code/lucy_r5.md",
        ".take_root/code/peter_r5.md",
    ]
    assert any("advance" in item for item in view["follow_ups"])


def test_write_run_summary_writes_fixed_path(tmp_path: Path) -> None:
    load_or_create_state(tmp_path)
    state = {
        "current_phase": "code",
        "phases": {
            "plan": {"status": "done", "final_plan_path": ".take_root/plan/final_plan.md"},
            "code": {
                "status": "done",
                "result": "exhausted_stop",
                "advance_allowed": False,
                "next_action": "take-root code --max-rounds 6",
                "last_max_rounds": 5,
                "rounds": [],
            },
            "test": {"status": "not_started", "iterations": [], "all_pass": False},
        },
    }

    path = write_run_summary(tmp_path, state)
    parsed = read_frontmatter_file(path)

    assert path == tmp_path / ".take_root" / "run_summary.md"
    assert parsed.metadata["artifact"] == "run_summary"
    assert parsed.metadata["current_phase"] == "code"
    assert parsed.metadata["workflow_status"] == "blocked"
    assert "## 本次概览" in parsed.body
    assert "## 后续动作" in parsed.body
