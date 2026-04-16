from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from take_root.cli import _cmd_resume, _run_phase, build_parser, main
from take_root.errors import ArtifactError
from take_root.state import load_or_create_state


@pytest.mark.parametrize(
    ("argv",),
    [
        (["init", "--help"],),
        (["configure", "--help"],),
        (["doctor", "--help"],),
        (["plan", "--help"],),
        (["code", "--help"],),
        (["test", "--help"],),
        (["run", "--help"],),
        (["reset", "--help"],),
        (["status", "--help"],),
        (["resume", "--help"],),
        (["logs", "--help"],),
    ],
)
def test_subcommand_help(argv: list[str]) -> None:
    parser: argparse.ArgumentParser = build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(argv)
    assert excinfo.value.code == 0


def test_parse_basic_plan_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["plan", "--max-rounds", "3", "--reference", "a.md"])
    assert args.command == "plan"
    assert args.max_rounds == 3


def test_parse_doctor_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor", "--persona", "jeff", "--no-call"])
    assert args.command == "doctor"
    assert args.persona == "jeff"
    assert args.no_call is True


def test_parse_doctor_all_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor", "--persona", "all"])
    assert args.command == "doctor"
    assert args.persona == "all"


def test_parse_reset_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["reset", "--all", "--yes"])
    assert args.command == "reset"
    assert args.all is True
    assert args.yes is True


def test_parse_reset_to_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["reset", "--to", "code", "--yes"])
    assert args.command == "reset"
    assert args.to == "code"
    assert args.yes is True


def test_parse_reset_rejects_all_with_to() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["reset", "--all", "--to", "code"])
    assert excinfo.value.code == 2


def test_parse_code_on_code_exhausted_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["code", "--on-code-exhausted", "advance"])
    assert args.command == "code"
    assert args.on_code_exhausted == "advance"


def test_parse_run_on_code_exhausted_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--on-code-exhausted", "stop", "--no-checkpoint"])
    assert args.command == "run"
    assert args.on_code_exhausted == "stop"
    assert args.no_checkpoint is True


def test_run_phase_passes_on_code_exhausted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_code(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr("take_root.cli.run_code", _fake_run_code)
    args = argparse.Namespace(
        plan=None,
        max_rounds=7,
        vcs="git",
        on_code_exhausted="advance",
    )

    _run_phase("code", tmp_path, args)

    assert captured["project_root"] == tmp_path
    assert captured["max_rounds"] == 7
    assert captured["vcs_mode"] == "git"
    assert captured["on_code_exhausted"] == "advance"


def test_cmd_resume_stops_on_exhausted_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = {
        "current_phase": "code",
        "phases": {
            "code": {
                "result": "exhausted_stop",
                "next_action": "take-root code --max-rounds 6",
            }
        },
    }
    called = {"code": False}

    def _fake_run_code(**kwargs: object) -> dict[str, object]:
        del kwargs
        called["code"] = True
        return {}

    monkeypatch.setattr("take_root.cli.reconcile_state_from_disk", lambda project_root: state)
    monkeypatch.setattr("take_root.cli.run_code", _fake_run_code)

    rc = _cmd_resume(tmp_path, argparse.Namespace())

    captured = capsys.readouterr()
    assert rc == 0
    assert called["code"] is False
    assert "take-root code --max-rounds 6" in captured.err


def test_main_refreshes_run_summary_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    load_or_create_state(tmp_path)

    def _raise_artifact_error(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise ArtifactError("boom")

    monkeypatch.setattr("take_root.cli.run_code", _raise_artifact_error)

    rc = main(["--project", str(tmp_path), "code"])

    assert rc == 4
    assert (tmp_path / ".take_root" / "run_summary.md").exists()
