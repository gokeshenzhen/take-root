from __future__ import annotations

import argparse

import pytest

from take_root.cli import build_parser


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
