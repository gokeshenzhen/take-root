from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from take_root.config import (
    ActorRouteConfig,
    default_take_root_config,
    resolve_persona_runtime_config,
)
from take_root.phase_ui import (
    _extract_peer_response,
    _extract_top_concerns,
    announce_persona_call,
    build_runtime_tag,
    render_artifact_summary,
)
from take_root.ui import Spinner, colorize


class _FakeStream(io.StringIO):
    def __init__(self, *, isatty_value: bool) -> None:
        super().__init__()
        self._isatty_value = isatty_value

    def isatty(self) -> bool:
        return self._isatty_value


def test_colorize_wraps_tty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(isatty_value=True)
    monkeypatch.setattr("take_root.ui.sys.stderr", stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TAKE_ROOT_DISABLE_COLOR", raising=False)

    assert colorize("hello", "cyan") == "\x1b[36mhello\x1b[0m"


def test_colorize_respects_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(isatty_value=True)
    monkeypatch.setattr("take_root.ui.sys.stderr", stream)
    monkeypatch.setenv("NO_COLOR", "1")

    assert colorize("hello", "cyan") == "hello"


def test_spinner_emits_single_line_on_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(isatty_value=False)
    monkeypatch.setattr("take_root.ui.sys.stderr", stream)

    with Spinner("phase call in progress") as spinner:
        pass

    assert "phase call in progress" in stream.getvalue()
    assert spinner.elapsed_sec >= 0.0


def test_build_runtime_tag_uses_resolved_model() -> None:
    resolved = resolve_persona_runtime_config(default_take_root_config(), "lucy")

    assert build_runtime_tag(resolved) == "gpt-5.4 · high"


def test_build_runtime_tag_reflects_configured_persona() -> None:
    config = default_take_root_config()
    config = replace(
        config,
        personas={
            **config.personas,
            "lucy": ActorRouteConfig(provider="codex_official", model="sonnet", effort="low"),
        },
    )

    resolved = resolve_persona_runtime_config(config, "lucy")

    assert build_runtime_tag(resolved) == "gpt-5.4-mini · low"


def test_announce_persona_call_renders_inputs_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stream = _FakeStream(isatty_value=False)
    monkeypatch.setattr("take_root.ui.sys.stderr", stream)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    announce_persona_call(
        phase="plan",
        round_num=2,
        persona="robin",
        action="评审中",
        inputs=[
            Path(".take_root/plan/jeff_proposal.md"),
            Path(".take_root/plan/neo_r1.md"),
        ],
        output=Path(".take_root/plan/robin_r2.md"),
        runtime_tag="qwen3-max · high",
    )

    rendered = stream.getvalue()
    assert "[plan r2] Robin 评审中" in rendered
    assert "in : .take_root/plan/jeff_proposal.md, .take_root/plan/neo_r1.md" in rendered
    assert "out: .take_root/plan/robin_r2.md" in rendered


def test_announce_persona_call_includes_runtime_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _FakeStream(isatty_value=False)
    monkeypatch.setattr("take_root.ui.sys.stderr", stream)

    announce_persona_call(
        phase="code",
        round_num=1,
        persona="lucy",
        action="实现中",
        inputs=[],
        output=Path(".take_root/code/lucy_r1.md"),
        runtime_tag="gpt-5.4 · high",
    )

    assert "(gpt-5.4 · high)" in stream.getvalue()


def test_render_artifact_summary_for_robin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "robin_r2.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: robin_review\n"
            "round: 2\n"
            "status: ongoing\n"
            "addresses: neo_r1.md\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "remaining_concerns: 2\n"
            "---\n"
            "# Robin — Round 2 Review\n\n"
            "## 1. 对 Neo 的回应\n"
            "### J1.1 回应\n"
            "- **立场**: 同意\n\n"
            "## 2. 新发现 / 我的关切\n"
            "### [BLOCKER] run_code dirty tree\n\n"
            "## 3. 收敛评估\n"
            "- **我的判断**: ongoing\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="robin",
        elapsed_sec=12.0,
        runtime_tag="qwen3-max · high",
    )

    captured = capsys.readouterr()
    assert "robin_r2  status=ongoing  concerns=2  addresses=neo_r1.md" in captured.err
    assert "回应 Neo: J1.1 同意" in captured.err
    assert "新关切: [BLOCKER] run_code dirty tree" in captured.err


def test_render_artifact_summary_with_timings_suffix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "robin_r1.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: robin_review\n"
            "round: 1\n"
            "status: ongoing\n"
            "addresses: jeff_proposal.md\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "remaining_concerns: 1\n"
            "---\n"
            "# Robin — Round 1 Review\n\n"
            "## 2. 新发现 / 我的关切\n"
            "### [MINOR] baseline\n\n"
            "## 3. 收敛评估\n"
            "- **我的判断**: ongoing\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="robin",
        elapsed_sec=12.0,
        runtime_tag="qwen3-max · high",
        timings={"wall_sec": 12.0, "llm_sec": 10.0, "harness_overhead_pct": 16.7},
    )

    captured = capsys.readouterr()
    assert "(12s · LLM 10s · overhead 16.7%)" in captured.err


def test_render_artifact_summary_lucy_show_commit_and_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "lucy_r2.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: lucy_implementation\n"
            "round: 2\n"
            "status: ongoing\n"
            "addresses: peter_r1.md\n"
            "vcs_mode: git\n"
            "commit_sha: abcdef1234567890\n"
            "snapshot_dir: null\n"
            "files_changed:\n"
            "  - src/take_root/ui.py\n"
            "  - src/take_root/phase_ui.py\n"
            "  - src/take_root/phases/plan.py\n"
            "  - tests/test_phase_ui.py\n"
            "  - tests/test_plan.py\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "open_pushbacks: 1\n"
            "---\n"
            "# Lucy — Round 2 Implementation\n\n"
            "## 3. 实现决策\n"
            "- 复用现有 ui 输出函数。\n\n"
            "## 4. 遗留工作 / 已知限制\n"
            "- doctor 集成暂未展开。\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="lucy",
        elapsed_sec=14.0,
        runtime_tag="gpt-5.4 · high",
    )

    captured = capsys.readouterr()
    assert "lucy_r2  status=ongoing  pushbacks=1  commit=abcdef1  files=5" in captured.err
    assert "files: src/take_root/ui.py, src/take_root/phase_ui.py," in captured.err
    assert "tests/test_plan.py" not in captured.err


def test_render_artifact_summary_tolerant_to_missing_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "robin_r2.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: robin_review\n"
            "round: 2\n"
            "status: ongoing\n"
            "addresses: neo_r1.md\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "remaining_concerns: 1\n"
            "---\n"
            "# Robin — Round 2 Review\n\n"
            "## 3. 收敛评估\n"
            "- **我的判断**: ongoing\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="robin",
        elapsed_sec=6.0,
        runtime_tag="qwen3-max · high",
    )

    captured = capsys.readouterr()
    assert "robin_r2  status=ongoing  concerns=1  addresses=neo_r1.md" in captured.err
    assert "回应 Neo:" not in captured.err
    assert "新关切:" not in captured.err


def test_render_artifact_summary_for_peter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "peter_r1.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: peter_review\n"
            "round: 1\n"
            "status: converged\n"
            "addresses: lucy_r1.md\n"
            "reviewed_commit: abcdef1234567\n"
            "files_reviewed: [src/take_root/ui.py]\n"
            "open_findings: 0\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "---\n"
            "# Peter — Round 1 Code Review\n\n"
            "## 2. 新发现\n\n"
            "## 4. 收敛评估\n"
            "- **我的判断**: converged\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="peter",
        elapsed_sec=9.0,
        runtime_tag="gpt-5.4 · high",
    )

    captured = capsys.readouterr()
    assert "peter_r1  (gpt-5.4 · high) ── converged · 0 open" in captured.err
    assert "reviewed=abcdef1  elapsed=9s" in captured.err


def test_render_artifact_summary_for_peter_with_timings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "peter_r2.md"
    artifact.write_text(
        (
            "---\n"
            "artifact: peter_review\n"
            "round: 2\n"
            "status: converged\n"
            "addresses: lucy_r2.md\n"
            "reviewed_commit: abcdef1234567\n"
            "files_reviewed: [src/take_root/ui.py]\n"
            "open_findings: 0\n"
            "created_at: 2026-04-18T00:00:00Z\n"
            "---\n"
            "# Peter — Round 2 Code Review\n\n"
            "## 2. 新发现\n\n"
            "## 4. 收敛评估\n"
            "- **我的判断**: converged\n"
        ),
        encoding="utf-8",
    )

    render_artifact_summary(
        artifact,
        persona="peter",
        elapsed_sec=9.0,
        runtime_tag="gpt-5.4 · high",
        timings={"wall_sec": 9.0, "llm_sec": 8.0, "harness_overhead_pct": 11.1},
    )

    captured = capsys.readouterr()
    assert "elapsed=9s · LLM 8s · overhead 11.1%" in captured.err


def test_extract_peer_response_multiple_stances() -> None:
    body = (
        "## 1. 对 Neo 的回应\n"
        "### J1.1 标题一\n"
        "- **立场**: 同意\n\n"
        "### J1.2 标题二\n"
        "- **立场**: 部分同意\n\n"
        "### J1.3 标题三\n"
        "- **立场**: 不同意\n\n"
        "## 2. 新发现 / 我的关切\n"
    )

    assert _extract_peer_response(body) == [
        ("J1.1", "同意"),
        ("J1.2", "部分同意"),
        ("J1.3", "不同意"),
    ]


def test_extract_top_concerns_respects_max_items() -> None:
    body = (
        "## 2. 新发现 / 我的关切\n"
        "### [BLOCKER] 一\n"
        "### [MAJOR] 二\n"
        "### [MINOR] 三\n"
        "## 3. 收敛评估\n"
    )

    assert _extract_top_concerns(body, max_items=2) == ["[BLOCKER] 一", "[MAJOR] 二"]
