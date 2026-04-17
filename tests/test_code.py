from __future__ import annotations

from pathlib import Path
from typing import Any

from take_root.config import default_take_root_config, save_config
from take_root.phases.code import _resolved_vcs_metadata, run_code
from take_root.runtimes.base import RuntimeCallResult
from take_root.state import load_or_create_state, transition


def test_resolved_vcs_metadata_falls_back_to_ruby_artifact_values() -> None:
    ruby_meta = {
        "commit_sha": "138e300d9b6e8daadd93830a0229c9b061caded3",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        ruby_meta,
        {"commit_sha": None, "snapshot_dir": None},
    )

    assert result["commit_sha"] == "138e300d9b6e8daadd93830a0229c9b061caded3"
    assert result["snapshot_dir"] == ".take_root/code/snapshots/r1"


def test_resolved_vcs_metadata_prefers_new_vcs_result() -> None:
    ruby_meta = {
        "commit_sha": "old-sha",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        ruby_meta,
        {"commit_sha": "new-sha", "snapshot_dir": ".take_root/code/snapshots/r2"},
    )

    assert result["commit_sha"] == "new-sha"
    assert result["snapshot_dir"] == ".take_root/code/snapshots/r2"


def _write_final_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "artifact: final_plan\n"
            "version: 1\n"
            "project_root: x\n"
            "based_on: jeff_proposal.md\n"
            "negotiation_rounds: 1\n"
            "converged: true\n"
            "created_at: 2026-04-17T00:00:00Z\n"
            "---\n"
            "# 最终方案：demo\n"
        ),
        encoding="utf-8",
    )


def _write_ruby_artifact(path: Path, *, round_num: int, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "artifact: ruby_implementation\n"
            f"round: {round_num}\n"
            f"status: {status}\n"
            "addresses: final_plan.md\n"
            "vcs_mode: off\n"
            "commit_sha: null\n"
            "snapshot_dir: null\n"
            "files_changed: []\n"
            "created_at: 2026-04-17T00:00:00Z\n"
            "open_pushbacks: 0\n"
            "---\n"
            "# Ruby\n"
        ),
        encoding="utf-8",
    )


def _write_peter_artifact(path: Path, *, round_num: int, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "artifact: peter_review\n"
            f"round: {round_num}\n"
            f"status: {status}\n"
            f"addresses: ruby_r{round_num}.md\n"
            "reviewed_commit: null\n"
            "files_reviewed: []\n"
            "open_findings: 0\n"
            "created_at: 2026-04-17T00:00:00Z\n"
            "---\n"
            "# Peter\n"
        ),
        encoding="utf-8",
    )


class _FakeRuntime:
    def __init__(
        self,
        persona_name: str,
        calls: list[Path],
        *,
        skip_first_peter_write: bool = False,
    ) -> None:
        self.persona_name = persona_name
        self.calls = calls
        self.skip_first_peter_write = skip_first_peter_write
        self.peter_attempts = 0

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 1800,
        policy: Any | None = None,
    ) -> RuntimeCallResult:
        del timeout_sec, policy
        output_line = next(
            line for line in boot_message.splitlines() if line.startswith("output_path: ")
        )
        output_path = Path(output_line.split(": ", 1)[1])
        self.calls.append(output_path)
        if self.persona_name == "ruby":
            round_num = int(output_path.stem.rsplit("r", 1)[1])
            _write_ruby_artifact(output_path, round_num=round_num, status="converged")
        else:
            round_num = int(output_path.stem.rsplit("r", 1)[1])
            self.peter_attempts += 1
            if self.skip_first_peter_write and self.peter_attempts == 1:
                return RuntimeCallResult(0, "", "", 0.1)
            _write_peter_artifact(output_path, round_num=round_num, status="converged")
        return RuntimeCallResult(0, "", "", 0.1)


def test_run_code_resumes_partial_round_with_peter_review_first(
    monkeypatch, tmp_path: Path
) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_final_plan(tmp_path / ".take_root" / "plan" / "final_plan.md")
    _write_ruby_artifact(tmp_path / ".take_root" / "code" / "ruby_r1.md", round_num=1, status="converged")
    transition(
        tmp_path,
        {
            "current_phase": "code",
            "phases": {
                "init": {
                    "done": True,
                    "claude_md_generated": True,
                    "claude_md_last_refresh": "2026-04-17T00:00:00Z",
                    "agents_md_symlinked": True,
                },
                "plan": {
                    "status": "done",
                    "final_plan_path": ".take_root/plan/final_plan.md",
                    "converged": True,
                },
            },
        },
    )
    calls: list[Path] = []
    monkeypatch.setattr("take_root.phases.code._check_runtime_available", lambda _: None)
    monkeypatch.setattr(
        "take_root.phases.code._runtime_for",
        lambda persona, project_root, config: _FakeRuntime(persona.name, calls),
    )

    state = run_code(tmp_path, vcs_mode="off", max_rounds=2)

    assert calls[0] == tmp_path / ".take_root" / "code" / "peter_r1.md"
    assert state["phases"]["code"]["status"] == "done"
    assert state["phases"]["code"]["rounds"][0]["peter_path"] == ".take_root/code/peter_r1.md"


def test_run_code_retries_missing_peter_artifact_once(monkeypatch, tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_final_plan(tmp_path / ".take_root" / "plan" / "final_plan.md")
    _write_ruby_artifact(tmp_path / ".take_root" / "code" / "ruby_r1.md", round_num=1, status="converged")
    transition(
        tmp_path,
        {
            "current_phase": "code",
            "phases": {
                "init": {
                    "done": True,
                    "claude_md_generated": True,
                    "claude_md_last_refresh": "2026-04-17T00:00:00Z",
                    "agents_md_symlinked": True,
                },
                "plan": {
                    "status": "done",
                    "final_plan_path": ".take_root/plan/final_plan.md",
                    "converged": True,
                },
            },
        },
    )
    calls: list[Path] = []
    monkeypatch.setattr("take_root.phases.code._check_runtime_available", lambda _: None)
    monkeypatch.setattr(
        "take_root.phases.code._runtime_for",
        lambda persona, project_root, config: _FakeRuntime(
            persona.name,
            calls,
            skip_first_peter_write=(persona.name == "peter"),
        ),
    )

    state = run_code(tmp_path, vcs_mode="off", max_rounds=2)

    assert calls == [
        tmp_path / ".take_root" / "code" / "peter_r1.md",
        tmp_path / ".take_root" / "code" / "peter_r1.md",
    ]
    assert state["phases"]["code"]["status"] == "done"
    assert (tmp_path / ".take_root" / "code" / "peter_r1.md").exists()
