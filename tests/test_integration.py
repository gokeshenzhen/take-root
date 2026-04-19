from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from take_root.cli import main
from take_root.config import default_take_root_config, save_config
from take_root.phases.init import run_init
from take_root.phases.plan import run_plan
from take_root.runtimes.base import RuntimeCallResult, RuntimePolicy
from take_root.state import load_or_create_state, transition

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.getenv("PYTEST_INTEGRATION") != "1":
        pytest.skip("integration tests require PYTEST_INTEGRATION=1")


def test_init_fresh_project_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _skip_if_disabled()
    save_config(tmp_path, default_take_root_config())
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
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
    save_config(tmp_path, default_take_root_config())
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_KIMI", "moonshot-token")
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
            self,
            boot_message: str,
            cwd: Path,
            timeout_sec: int = 900,
            policy: RuntimePolicy | None = None,
        ) -> RuntimeCallResult:
            del timeout_sec, policy
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
                        "# Robin — Round 1 Review\n\n"
                        "## 2. 新发现 / 我的关切\n"
                        "### [MINOR] x\n"
                        "- **位置**: jeff_proposal.md § 1\n\n"
                        "## 3. 收敛评估\n"
                        "- **我的判断**: converged\n"
                    ),
                    encoding="utf-8",
                )
            elif output_path.name.startswith("neo_r"):
                output_path.write_text(
                    (
                        "---\n"
                        "artifact: neo_review\n"
                        "round: 1\n"
                        "status: converged\n"
                        "addresses: robin_r1.md\n"
                        "created_at: 2026-04-14T00:00:00Z\n"
                        "open_attacks: 0\n"
                        "---\n"
                        "# Neo — Round 1 Adversarial Review\n\n"
                        "## 2. 新攻击点\n"
                        "### J1.1 [MINOR] x\n"
                        "- **攻击对象**: robin_r1.md § 1\n\n"
                        "## 3. 收敛评估\n"
                        "- **我的判断**: converged\n"
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
                        "# 最终方案：demo\n\n"
                        "## 1. 目标\n"
                        "## 2. 非目标\n"
                        "## 3. 背景与约束\n"
                        "## 4. 设计概览\n"
                        "## 5. 关键决策\n"
                        "## 6. 实施步骤\n"
                        "## 7. 验收标准\n"
                        "## 8. 已知风险与未决问题\n"
                    ),
                    encoding="utf-8",
                )
            return RuntimeCallResult(0, "", "", 0.1)

    monkeypatch.setattr(
        "take_root.phases.plan.runtime_for",
        lambda persona, project_root, config: FakeRuntime(),
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


def test_run_on_code_exhausted_stops_before_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_if_disabled()
    phases_called: list[str] = []
    monkeypatch.setattr(
        "take_root.cli.load_or_create_state",
        lambda project_root: {"phases": {"init": {"done": True}}},
    )

    def _fake_run_phase(name: str, project_root: Path, args: Any) -> dict[str, Any]:
        del project_root, args
        phases_called.append(name)
        if name == "code":
            return {
                "phases": {
                    "code": {
                        "result": "exhausted_stop",
                        "next_action": "take-root code --max-rounds 6",
                    }
                }
            }
        raise AssertionError("test phase should not run after exhausted_stop")

    monkeypatch.setattr("take_root.cli._run_phase", _fake_run_phase)

    rc = main(["--project", str(tmp_path), "run", "--phases", "code,test", "--no-checkpoint"])

    assert rc == 0
    assert phases_called == ["code"]


def test_status_summary_view(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _skip_if_disabled()
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
    monkeypatch.setattr("take_root.cli.reconcile_state_from_disk", lambda project_root: state)

    rc = main(["--project", str(tmp_path), "status"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "当前结论: blocked" in captured.out
    assert "下一步: take-root code --max-rounds 6" in captured.out
