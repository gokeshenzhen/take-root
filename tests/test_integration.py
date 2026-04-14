from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from take_root.cli import main
from take_root.phases.init import run_init
from take_root.phases.plan import run_plan
from take_root.runtimes.base import RuntimeCallResult
from take_root.state import load_or_create_state, transition

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.getenv("PYTEST_INTEGRATION") != "1":
        pytest.skip("integration tests require PYTEST_INTEGRATION=1")


def test_init_fresh_project_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _skip_if_disabled()
    monkeypatch.setattr("take_root.phases.init.ClaudeRuntime.check_available", lambda: None)
    monkeypatch.setattr(
        "take_root.phases.init._generate_claude_md",
        lambda project_root, refresh: "# Project\n\n- context\n",
    )
    run_init(tmp_path)
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".take_root" / "state.json").exists()


def test_plan_phase_with_mocked_runtimes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _skip_if_disabled()
    load_or_create_state(tmp_path)
    transition(
        tmp_path,
        {
            "phases": {
                "init": {
                    "done": True,
                    "claude_md_generated": True,
                    "claude_md_last_refresh": "2026-04-14T00:00:00Z",
                    "agents_md_symlinked": True,
                }
            }
        },
    )
    (tmp_path / "CLAUDE.md").write_text("# ctx\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    (tmp_path / ".take_root" / "plan").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("take_root.phases.plan.ClaudeRuntime.check_available", lambda: None)
    monkeypatch.setattr("take_root.phases.plan._maybe_refresh_claude_md", lambda project_root: None)

    class FakeRuntime:
        def call_interactive(self, boot_message: str, cwd: Path) -> RuntimeCallResult:
            del boot_message
            path = cwd / ".take_root" / "plan" / "jeff_proposal.md"
            path.write_text(
                (
                    "---\n"
                    "artifact: jeff_proposal\n"
                    "version: 1\n"
                    "status: draft\n"
                    "project_root: x\n"
                    "references: []\n"
                    "created_at: 2026-04-14T00:00:00Z\n"
                    "---\n"
                    "# 提案\n"
                ),
                encoding="utf-8",
            )
            return RuntimeCallResult(0, "", "", 0.1)

        def call_noninteractive(
            self, boot_message: str, cwd: Path, timeout_sec: int = 900
        ) -> RuntimeCallResult:
            del timeout_sec
            output_line = next(
                line for line in boot_message.splitlines() if line.startswith("output_path: ")
            )
            output_path = Path(output_line.split(": ", 1)[1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.name.startswith("robin_r"):
                output_path.write_text(
                    (
                        "---\n"
                        "artifact: robin_review\n"
                        "round: 1\n"
                        "status: converged\n"
                        "addresses: jeff_proposal.md\n"
                        "created_at: 2026-04-14T00:00:00Z\n"
                        "remaining_concerns: 0\n"
                        "---\n"
                        "# robin\n"
                    ),
                    encoding="utf-8",
                )
            elif output_path.name.startswith("jack_r"):
                output_path.write_text(
                    (
                        "---\n"
                        "artifact: jack_review\n"
                        "round: 1\n"
                        "status: converged\n"
                        "addresses: robin_r1.md\n"
                        "created_at: 2026-04-14T00:00:00Z\n"
                        "open_attacks: 0\n"
                        "---\n"
                        "# jack\n"
                    ),
                    encoding="utf-8",
                )
            else:
                output_path.write_text(
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
            return RuntimeCallResult(0, "", "", 0.1)

    monkeypatch.setattr(
        "take_root.phases.plan._runtime_for", lambda persona, project_root: FakeRuntime()
    )
    state = run_plan(tmp_path, max_rounds=2)
    assert state["phases"]["plan"]["status"] == "done"
    assert (tmp_path / ".take_root" / "plan" / "final_plan.md").exists()


def test_resume_dispatches_to_pending_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_if_disabled()
    load_or_create_state(tmp_path)
    transition(
        tmp_path,
        {
            "current_phase": "code",
            "phases": {
                "init": {"done": True},
                "plan": {"status": "done"},
            },
        },
    )
    called: dict[str, bool] = {"code": False}

    def _fake_code(**kwargs: Any) -> dict[str, Any]:
        called["code"] = True
        return {}

    monkeypatch.setattr("take_root.cli.run_code", _fake_code)
    monkeypatch.setattr(
        "take_root.cli.reconcile_state_from_disk",
        lambda project_root: load_or_create_state(tmp_path),
    )
    rc = main(["--project", str(tmp_path), "resume"])
    assert rc == 0
    assert called["code"] is True
