from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from take_root.guardrails import scan_review_context, snapshot_workspace
from take_root.state import load_or_create_state, reconcile_state_from_disk, transition

pytestmark = pytest.mark.perf


@pytest.fixture
def small_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    for index in range(50):
        (tmp_path / "src" / f"f{index}.py").write_text("x = 1\n" * 20, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# test\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def medium_workspace(tmp_path: Path) -> Path:
    for directory_index in range(10):
        subdir = tmp_path / f"pkg{directory_index}"
        subdir.mkdir()
        for file_index in range(50):
            (subdir / f"m{file_index}.py").write_text("x = 1\n" * 200, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# test\n", encoding="utf-8")
    return tmp_path


def test_snapshot_small(benchmark, small_workspace: Path) -> None:
    output_path = small_workspace / ".take_root" / "plan" / "robin_r1.md"
    output_path.parent.mkdir(parents=True)
    benchmark(snapshot_workspace, small_workspace, output_path)


def test_snapshot_medium(benchmark, medium_workspace: Path) -> None:
    output_path = medium_workspace / ".take_root" / "plan" / "robin_r1.md"
    output_path.parent.mkdir(parents=True)
    benchmark(snapshot_workspace, medium_workspace, output_path)


def test_scan_review_context_small(benchmark, small_workspace: Path) -> None:
    files = sorted((small_workspace / "src").rglob("*.py"))[:20]
    benchmark(scan_review_context, files)


def test_reconcile_state_empty(benchmark, tmp_path: Path) -> None:
    (tmp_path / ".take_root").mkdir()
    benchmark(reconcile_state_from_disk, tmp_path)


def test_end_to_end_plan_with_fake_runtime(benchmark, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TAKE_ROOT_RUNTIME_OVERRIDE", "fake")
    monkeypatch.setenv("TAKE_ROOT_FAKE_DELAY_MS", "5")
    monkeypatch.setenv(
        "TAKE_ROOT_FAKE_FIXTURE_DIR", str(Path(__file__).parent / "fixtures" / "artifacts")
    )
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "qwen-token")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_KIMI", "kimi-token")
    _bootstrap_configured_project(tmp_path)

    from take_root.phases.plan import run_plan

    def _run() -> None:
        _reset_plan_artifacts(tmp_path)
        run_plan(tmp_path, reference_files=[], no_brainstorm=True, max_rounds=2)

    benchmark(_run)


def _bootstrap_configured_project(project_root: Path) -> None:
    fixture_root = Path(__file__).parent / "fixtures"
    plan_dir = project_root / ".take_root" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_root / "config.yaml", project_root / ".take_root" / "config.yaml")
    (project_root / "CLAUDE.md").write_text("# benchmark\n", encoding="utf-8")
    agents_path = project_root / "AGENTS.md"
    if agents_path.exists() or agents_path.is_symlink():
        agents_path.unlink()
    agents_path.symlink_to("CLAUDE.md")
    shutil.copyfile(fixture_root / "artifacts" / "jeff.md", plan_dir / "jeff_proposal.md")
    load_or_create_state(project_root)
    transition(
        project_root,
        {
            "phases": {
                "init": {
                    "done": True,
                    "claude_md_generated": True,
                    "claude_md_last_refresh": "2026-04-19T00:00:00Z",
                    "agents_md_symlinked": True,
                }
            }
        },
    )


def _reset_plan_artifacts(project_root: Path) -> None:
    plan_dir = project_root / ".take_root" / "plan"
    for entry in plan_dir.glob("robin_r*.md"):
        entry.unlink()
    for entry in plan_dir.glob("neo_r*.md"):
        entry.unlink()
    final_plan = plan_dir / "final_plan.md"
    if final_plan.exists():
        final_plan.unlink()
    perf_log = project_root / ".take_root" / "perf" / "plan.jsonl"
    if perf_log.exists():
        perf_log.unlink()
