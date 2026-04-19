from __future__ import annotations

import io
from pathlib import Path

import pytest

from take_root.ui import print_status, select_option


def test_select_option_accepts_arrow_navigation() -> None:
    keys = iter(["down", "enter"])
    output = io.StringIO()
    selected = select_option(
        "选择 provider",
        ["claude_official", "codex_official"],
        "claude_official",
        output=output,
        key_reader=lambda stream: next(keys),
        interactive=True,
    )
    rendered = output.getvalue()
    assert selected == "codex_official"
    assert "●" in rendered


def test_print_status_uses_summary_view(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = {
        "current_phase": "code",
        "phases": {
            "plan": {"status": "done", "final_plan_path": ".take_root/plan/final_plan.md"},
            "code": {
                "status": "done",
                "result": "exhausted_stop",
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

    print_status(state, tmp_path)

    captured = capsys.readouterr()
    assert "当前结论: blocked" in captured.out
    assert "下一步: take-root code --max-rounds 6" in captured.out
