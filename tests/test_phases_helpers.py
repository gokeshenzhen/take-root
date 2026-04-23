from __future__ import annotations

from pathlib import Path

import pytest

from take_root.errors import ArtifactError
from take_root.phases import format_boot_message, validate_artifact


def test_format_boot_message_basic() -> None:
    message = format_boot_message(
        "demo",
        project_root="/tmp/p",
        reference_files=["/tmp/a.md"],
        flag=True,
        nothing=None,
    )
    assert message.startswith("[take-root harness boot]")
    assert "flag: true" in message
    assert "nothing: null" in message


def test_format_boot_message_size_limit() -> None:
    with pytest.raises(ArtifactError):
        format_boot_message("demo", text="x" * (33 * 1024))


def test_validate_artifact_success(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("---\na: 1\nb: 2\n---\nbody\n", encoding="utf-8")
    meta = validate_artifact(path, ["a", "b"])
    assert meta["a"] == 1


def test_validate_artifact_without_timings(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("---\na: 1\nb: 2\n---\nbody\n", encoding="utf-8")

    meta = validate_artifact(path, ["a", "b"])

    assert "timings" not in meta


def test_validate_artifact_with_timings(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text(
        (
            "---\n"
            "a: 1\n"
            "b: 2\n"
            "timings:\n"
            "  wall_sec: 10.0\n"
            "  llm_sec: 8.0\n"
            "  harness_sec: 2.0\n"
            "  harness_overhead_pct: 20.0\n"
            "  breakdown:\n"
            "    validate_artifact_ms: 5\n"
            "    runtime_setup_ms: 1\n"
            "    runtime_teardown_ms: 1\n"
            "    retry_backoff_ms: 0\n"
            "---\n"
            "body\n"
        ),
        encoding="utf-8",
    )

    meta = validate_artifact(path, ["a", "b"])

    assert isinstance(meta["timings"], dict)


def test_validate_artifact_missing_required(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("---\na: 1\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ArtifactError):
        validate_artifact(path, ["a", "b"])


def test_validate_artifact_reports_frontmatter_parse_detail(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("not frontmatter\nartifact: nope\n", encoding="utf-8")

    with pytest.raises(ArtifactError, match=r"Invalid frontmatter in artifact: .*a\.md"):
        validate_artifact(path, ["a"])


def test_validate_robin_review_requires_convergence_section(tmp_path: Path) -> None:
    path = tmp_path / "robin_r2.md"
    path.write_text(
        (
            "---\n"
            "artifact: robin_review\n"
            "round: 2\n"
            "status: ongoing\n"
            "addresses: neo_r1.md\n"
            "created_at: 2026-04-16T00:00:00Z\n"
            "remaining_concerns: 1\n"
            "---\n"
            "# Robin — Round 2 Review\n\n"
            "## 1. 对 Neo 的回应\n"
            "### J1.1: x\n"
            "## 2. 新发现 / 我的关切\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="收敛评估"):
        validate_artifact(
            path,
            ["artifact", "round", "status", "addresses", "created_at", "remaining_concerns"],
        )


def test_validate_neo_review_requires_integer_open_attacks(tmp_path: Path) -> None:
    path = tmp_path / "neo_r1.md"
    path.write_text(
        (
            "---\n"
            "artifact: neo_review\n"
            "round: 1\n"
            "status: ongoing\n"
            "addresses: robin_r1.md\n"
            "created_at: 2026-04-16T00:00:00Z\n"
            "open_attacks: nope\n"
            "---\n"
            "# Neo — Round 1 Adversarial Review\n\n"
            "## 2. 新攻击点\n\n"
            "## 3. 收敛评估\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="open_attacks"):
        validate_artifact(
            path,
            ["artifact", "round", "status", "addresses", "created_at", "open_attacks"],
        )


def test_validate_final_plan_requires_expected_sections(tmp_path: Path) -> None:
    path = tmp_path / "final_plan.md"
    path.write_text(
        (
            "---\n"
            "artifact: final_plan\n"
            "version: 1\n"
            "project_root: /tmp/demo\n"
            "based_on: jeff_proposal.md\n"
            "negotiation_rounds: 1\n"
            "converged: true\n"
            "created_at: 2026-04-16T00:00:00Z\n"
            "---\n"
            "# 最终方案：demo\n\n"
            "## 1. 目标\n"
            "## 2. 非目标\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="背景与约束"):
        validate_artifact(
            path,
            [
                "artifact",
                "version",
                "project_root",
                "based_on",
                "negotiation_rounds",
                "converged",
                "created_at",
            ],
        )
