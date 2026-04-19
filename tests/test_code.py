from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from take_root.config import default_take_root_config, save_config
from take_root.frontmatter import read_frontmatter_file
from take_root.phases.code import _resolved_vcs_metadata, run_code
from take_root.runtimes.base import RuntimeCallResult
from take_root.state import load_or_create_state, transition


def test_resolved_vcs_metadata_falls_back_to_lucy_artifact_values() -> None:
    lucy_meta = {
        "commit_sha": "138e300d9b6e8daadd93830a0229c9b061caded3",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        lucy_meta,
        {"commit_sha": None, "snapshot_dir": None},
    )

    assert result["commit_sha"] == "138e300d9b6e8daadd93830a0229c9b061caded3"
    assert result["snapshot_dir"] == ".take_root/code/snapshots/r1"


def test_resolved_vcs_metadata_prefers_new_vcs_result() -> None:
    lucy_meta = {
        "commit_sha": "old-sha",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        lucy_meta,
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


def _write_lucy_artifact(path: Path, *, round_num: int, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "artifact: lucy_implementation\n"
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
            "# Lucy\n"
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
            f"addresses: lucy_r{round_num}.md\n"
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
        self.policies: list[Any | None] = []

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 1800,
        policy: Any | None = None,
    ) -> RuntimeCallResult:
        del timeout_sec
        output_line = next(
            line for line in boot_message.splitlines() if line.startswith("output_path: ")
        )
        output_path = Path(output_line.split(": ", 1)[1])
        self.calls.append(output_path)
        self.policies.append(policy)
        if self.persona_name == "lucy":
            round_num = int(output_path.stem.rsplit("r", 1)[1])
            _write_lucy_artifact(output_path, round_num=round_num, status="converged")
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
    _write_lucy_artifact(
        tmp_path / ".take_root" / "code" / "lucy_r1.md",
        round_num=1,
        status="converged",
    )
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
    monkeypatch.setattr("take_root.phases.code.check_runtime_available", lambda _: None)
    runtimes: dict[str, _FakeRuntime] = {}

    def _fake_runtime_for(persona, project_root, config):
        del project_root, config
        runtime = _FakeRuntime(persona.name, calls)
        runtimes[persona.name] = runtime
        return runtime

    monkeypatch.setattr("take_root.phases.code.runtime_for", _fake_runtime_for)

    state = run_code(tmp_path, vcs_mode="off", max_rounds=2)

    assert calls[0] == tmp_path / ".take_root" / "code" / "peter_r1.md"
    assert state["phases"]["code"]["status"] == "done"
    assert state["phases"]["code"]["rounds"][0]["peter_path"] == ".take_root/code/peter_r1.md"
    assert runtimes["peter"].policies[0] is not None
    assert runtimes["peter"].policies[0].mode == "review_only"
    assert (
        runtimes["peter"].policies[0].output_path
        == (tmp_path / ".take_root" / "code" / "peter_r1.md").resolve()
    )
    peter_meta = read_frontmatter_file(tmp_path / ".take_root" / "code" / "peter_r1.md").metadata
    assert "timings" in peter_meta
    perf_lines = (
        (tmp_path / ".take_root" / "perf" / "code.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(perf_lines) == 1
    assert isinstance(json.loads(perf_lines[0]), dict)


def test_run_code_retries_missing_peter_artifact_once(monkeypatch, tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_final_plan(tmp_path / ".take_root" / "plan" / "final_plan.md")
    _write_lucy_artifact(
        tmp_path / ".take_root" / "code" / "lucy_r1.md",
        round_num=1,
        status="converged",
    )
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
    monkeypatch.setattr("take_root.phases.code.check_runtime_available", lambda _: None)
    runtimes: dict[str, _FakeRuntime] = {}

    def _fake_runtime_for(persona, project_root, config):
        del project_root, config
        runtime = _FakeRuntime(
            persona.name,
            calls,
            skip_first_peter_write=(persona.name == "peter"),
        )
        runtimes[persona.name] = runtime
        return runtime

    monkeypatch.setattr("take_root.phases.code.runtime_for", _fake_runtime_for)

    state = run_code(tmp_path, vcs_mode="off", max_rounds=2)

    assert calls == [
        tmp_path / ".take_root" / "code" / "peter_r1.md",
        tmp_path / ".take_root" / "code" / "peter_r1.md",
    ]
    assert state["phases"]["code"]["status"] == "done"
    assert (tmp_path / ".take_root" / "code" / "peter_r1.md").exists()
    assert all(
        policy is not None and policy.mode == "review_only" for policy in runtimes["peter"].policies
    )


def test_run_code_prints_rich_phase_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_final_plan(tmp_path / ".take_root" / "plan" / "final_plan.md")
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
    monkeypatch.setattr("take_root.phases.code.check_runtime_available", lambda _: None)
    monkeypatch.setattr(
        "take_root.phases.code.runtime_for",
        lambda persona, project_root, config: _FakeRuntime(persona.name, calls),
    )

    run_code(tmp_path, vcs_mode="off", max_rounds=2)

    captured = capsys.readouterr()
    assert "[code r1] Lucy 实现中" in captured.err
    assert "lucy_r1  status=converged  pushbacks=0  commit=-  files=0" in captured.err
    assert "peter_r1  (gpt-5.4 · high) ── converged · 0 open" in captured.err
