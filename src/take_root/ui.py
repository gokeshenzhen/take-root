from __future__ import annotations

import sys
import termios
import tty
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from take_root.summary import build_summary_view


def info(message: str) -> None:
    print(message, file=sys.stderr)


def warn(message: str) -> None:
    print(f"警告: {message}", file=sys.stderr)


def error(message: str) -> None:
    print(f"错误: {message}", file=sys.stderr)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = ""
    if default is not None:
        suffix = f" [{default}]"
    answer = input(f"{prompt}{suffix}: ").strip()
    if not answer and default is not None:
        return default
    return answer


def _fallback_select_option(prompt: str, options: list[str], default: str) -> str:
    if default not in options:
        raise ValueError(f"default {default!r} not in options")
    default_index = options.index(default) + 1
    while True:
        info(prompt)
        for index, option in enumerate(options, start=1):
            suffix = " (default)" if index == default_index else ""
            info(f"  {index}. {option}{suffix}")
        answer = ask("请输入编号，直接回车使用默认", default=str(default_index))
        if answer.isdigit():
            selected_index = int(answer)
            if 1 <= selected_index <= len(options):
                return options[selected_index - 1]
        info("无效选择，请输入列表中的编号")


def _read_menu_key(input_stream: TextIO) -> str:
    fd = input_stream.fileno()
    original_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = input_stream.read(1)
        if first in {"\r", "\n"}:
            return "enter"
        if first == "\x03":
            raise KeyboardInterrupt
        if first == "\x1b":
            second = input_stream.read(1)
            third = input_stream.read(1)
            if second == "[" and third == "A":
                return "up"
            if second == "[" and third == "B":
                return "down"
        return first
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)


def _render_select_menu(
    output: TextIO,
    prompt: str,
    options: list[str],
    selected_index: int,
    default_index: int,
) -> int:
    lines = [prompt]
    for index, option in enumerate(options):
        indicator = "\x1b[32m●\x1b[0m" if index == selected_index else "○"
        suffix = " (default)" if index == default_index else ""
        lines.append(f"  {indicator} {option}{suffix}")
    output.write("\n".join(lines))
    output.write("\n")
    output.flush()
    return len(lines)


def _clear_select_menu(output: TextIO, line_count: int) -> None:
    for _ in range(line_count):
        output.write("\x1b[1A")
        output.write("\r")
        output.write("\x1b[2K")
    output.flush()


def select_option(
    prompt: str,
    options: list[str],
    default: str,
    *,
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
    key_reader: Callable[[TextIO], str] | None = None,
    interactive: bool | None = None,
) -> str:
    if default not in options:
        raise ValueError(f"default {default!r} not in options")
    resolved_input = input_stream if input_stream is not None else sys.stdin
    resolved_output = output if output is not None else sys.stderr
    if interactive is None:
        interactive = resolved_input.isatty() and resolved_output.isatty()
    if not interactive:
        return _fallback_select_option(prompt, options, default)

    read_key = key_reader if key_reader is not None else _read_menu_key
    selected_index = options.index(default)
    default_index = selected_index
    line_count = _render_select_menu(
        resolved_output,
        prompt,
        options,
        selected_index,
        default_index,
    )
    while True:
        key = read_key(resolved_input)
        if key == "enter":
            resolved_output.write("\n")
            resolved_output.flush()
            return options[selected_index]
        if key == "up":
            selected_index = (selected_index - 1) % len(options)
        elif key == "down":
            selected_index = (selected_index + 1) % len(options)
        else:
            continue
        _clear_select_menu(resolved_output, line_count)
        line_count = _render_select_menu(
            resolved_output,
            prompt,
            options,
            selected_index,
            default_index,
        )


def checkpoint_prompt() -> str:
    return ask("是否继续下一阶段？输入 Y / n / save-and-exit", default="Y").lower()


def print_status(state: dict[str, Any], project_root: Path) -> None:
    view = build_summary_view(project_root, state)
    print(f"Project: {project_root}", file=sys.stdout)
    print(f"当前阶段: {view['current_phase']}", file=sys.stdout)
    print(f"当前结论: {view['workflow_status']}", file=sys.stdout)
    print(f"原因: {view['overview']}", file=sys.stdout)
    next_action = view.get("next_action")
    if isinstance(next_action, str) and next_action:
        print(f"下一步: {next_action}", file=sys.stdout)
