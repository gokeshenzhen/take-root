from __future__ import annotations

import json
from pathlib import Path

import pytest

from take_root.config import default_take_root_config, save_config
from take_root.frontmatter import read_frontmatter_file
from take_root.phases.test import run_test
from take_root.runtimes.base import RuntimeCallResult
from take_root.state import load_or_create_state


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
            "created_at: 2026-04-14T00:00:00Z\n"
            "---\n"
            "# final\n"
        ),
        encoding="utf-8",
    )


def _write_code_artifact(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (f"---\nartifact: demo\nstatus: {status}\ncreated_at: 2026-04-14T00:00:00Z\n---\n# 内容\n"),
        encoding="utf-8",
    )


def _write_amy_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "artifact: amy_test_report\n"
            "iteration: 1\n"
            "status: all_pass\n"
            "test_command: pytest\n"
            "tested_commit: abc123\n"
            "counts:\n"
            "  total: 111\n"
            "  passed: 111\n"
            "  fail: 0\n"
            "  error_code: 0\n"
            "  error_test: 0\n"
            "  error_env: 0\n"
            "  suspicious: 0\n"
            "  skipped: 0\n"
            "duration_sec: 0.62\n"
            "created_at: 2026-04-17T13:09:25+08:00\n"
            "---\n"
            "# Amy Report\n"
        ),
        encoding="utf-8",
    )


def test_run_test_prints_all_pass_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_config(tmp_path, default_take_root_config())
    load_or_create_state(tmp_path)
    _write_final_plan(tmp_path / ".take_root" / "plan" / "final_plan.md")
    _write_code_artifact(tmp_path / ".take_root" / "code" / "lucy_r1.md", "converged")
    _write_code_artifact(tmp_path / ".take_root" / "code" / "peter_r1.md", "converged")

    monkeypatch.setattr("take_root.phases.test.check_runtime_available", lambda runtime_name: None)

    class FakeRuntime:
        def call_noninteractive(
            self,
            boot_message: str,
            cwd: Path,
            timeout_sec: int = 900,
        ) -> RuntimeCallResult:
            del cwd, timeout_sec
            output_line = next(
                line for line in boot_message.splitlines() if line.startswith("output_path: ")
            )
            output_path = Path(output_line.split(": ", 1)[1])
            _write_amy_report(output_path)
            return RuntimeCallResult(0, "", "", 0.1)

    monkeypatch.setattr(
        "take_root.phases.test.runtime_for",
        lambda persona, project_root, config: FakeRuntime(),
    )

    state = run_test(tmp_path)

    captured = capsys.readouterr()
    assert state["current_phase"] == "done"
    assert "[test it1] Amy 全量测试中" in captured.err
    assert "amy_r1  status=all_pass  passed=111  fail=0" in captured.err
    assert "  - status: all_pass" in captured.err
    assert "  - counts.passed: 111" in captured.err
    assert "  - counts.fail: 0" in captured.err
    assert "  - counts.error_test: 0" in captured.err
    assert "  - counts.error_env: 0" in captured.err
    amy_meta = read_frontmatter_file(tmp_path / ".take_root" / "test" / "amy_r1.md").metadata
    assert "timings" in amy_meta
    perf_lines = (
        (tmp_path / ".take_root" / "perf" / "test.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(perf_lines) == 1
    assert isinstance(json.loads(perf_lines[0]), dict)
