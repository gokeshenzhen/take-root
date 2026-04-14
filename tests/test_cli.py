from __future__ import annotations

import argparse

import pytest

from take_root.cli import build_parser


@pytest.mark.parametrize(
    ("argv",),
    [
        (["init", "--help"],),
        (["plan", "--help"],),
        (["code", "--help"],),
        (["test", "--help"],),
        (["run", "--help"],),
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
