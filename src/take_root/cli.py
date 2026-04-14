from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from take_root.artifacts import list_artifact_files
from take_root.errors import ArtifactError, RuntimeCallError, TakeRootError, UserAbort
from take_root.phases.code import run_code
from take_root.phases.init import run_init
from take_root.phases.plan import run_plan
from take_root.phases.test import run_test
from take_root.state import load_or_create_state, reconcile_state_from_disk
from take_root.ui import checkpoint_prompt, error, info, print_status

LOGGER = logging.getLogger(__name__)


def _setup_logging(verbose: bool, log_file: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="[%(levelname)s] %(name)s: %(message)s",
    )


def _project_root(value: str | None) -> Path:
    return Path(value).resolve() if value else Path.cwd().resolve()


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, default=None, help="目标项目路径（默认当前目录）")
    parser.add_argument("-v", "--verbose", action="store_true", help="开启调试日志")
    parser.add_argument("--log-file", type=Path, default=None, help="日志输出文件路径")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="take-root", description="take-root CLI harness")
    _add_global_flags(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化 take-root 目录与上下文")
    init_parser.add_argument("--refresh", action="store_true", help="刷新 CLAUDE.md")
    init_parser.add_argument("--no-gitignore", action="store_true", help="不修改 .gitignore")

    plan_parser = subparsers.add_parser("plan", help="执行规划阶段")
    plan_parser.add_argument("--reference", action="append", default=[], type=Path, help="参考文件")
    plan_parser.add_argument(
        "--no-brainstorm", action="store_true", help="提示 Jeff 跳过 brainstorm"
    )
    plan_parser.add_argument("--max-rounds", type=int, default=5, help="Robin/Jack 最大轮数")

    code_parser = subparsers.add_parser("code", help="执行编码阶段")
    code_parser.add_argument("--plan", type=Path, default=None, help="final_plan.md 路径")
    code_parser.add_argument("--max-rounds", type=int, default=5, help="Ruby/Peter 最大轮数")
    code_parser.add_argument(
        "--vcs",
        choices=["git", "snapshot", "off", "auto"],
        default="auto",
        help="版本控制模式",
    )

    test_parser = subparsers.add_parser("test", help="执行测试阶段")
    test_parser.add_argument("--max-iterations", type=int, default=5, help="Amy 最大迭代次数")
    test_parser.add_argument(
        "--escalate",
        choices=["auto", "always", "never"],
        default="auto",
        help="达到上限后的处理策略",
    )

    run_parser = subparsers.add_parser("run", help="按顺序执行多个阶段")
    run_parser.add_argument("--phases", default="plan,code,test", help="逗号分隔：plan,code,test")
    run_parser.add_argument("--no-checkpoint", action="store_true", help="阶段间不暂停确认")

    subparsers.add_parser("status", help="查看当前状态")
    subparsers.add_parser("resume", help="从 state.json 继续执行")

    logs_parser = subparsers.add_parser("logs", help="查看 artifact 日志")
    logs_parser.add_argument("phase", nargs="?", choices=["plan", "code", "test"], default=None)
    logs_parser.add_argument("--round", type=int, default=None, help="查看指定轮次")
    return parser


def _run_phase(name: str, project_root: Path, args: argparse.Namespace) -> dict[str, object]:
    if name == "plan":
        references = [path.resolve() for path in getattr(args, "reference", [])]
        return run_plan(
            project_root=project_root,
            reference_files=references,
            no_brainstorm=bool(getattr(args, "no_brainstorm", False)),
            max_rounds=int(getattr(args, "max_rounds", 5)),
        )
    if name == "code":
        plan_arg = getattr(args, "plan", None)
        return run_code(
            project_root=project_root,
            plan_file=plan_arg.resolve() if isinstance(plan_arg, Path) else None,
            max_rounds=int(getattr(args, "max_rounds", 5)),
            vcs_mode=str(getattr(args, "vcs", "auto")),
        )
    if name == "test":
        return run_test(
            project_root=project_root,
            max_iterations=int(getattr(args, "max_iterations", 5)),
            escalate=str(getattr(args, "escalate", "auto")),
        )
    raise ValueError(f"unknown phase {name}")


def _should_continue(no_checkpoint: bool) -> bool:
    if no_checkpoint:
        return True
    answer = checkpoint_prompt()
    if answer in {"y", "yes", ""}:
        return True
    if answer == "save-and-exit":
        info("状态已保存，后续可执行: take-root resume")
        return False
    return False


def _cmd_logs(project_root: Path, phase: str | None, round_num: int | None) -> int:
    files = list_artifact_files(project_root, phase=phase)
    if round_num is not None and phase is not None:
        if phase == "plan":
            targets = [
                project_root / ".take_root" / "plan" / f"robin_r{round_num}.md",
                project_root / ".take_root" / "plan" / f"jack_r{round_num}.md",
            ]
        elif phase == "code":
            targets = [
                project_root / ".take_root" / "code" / f"ruby_r{round_num}.md",
                project_root / ".take_root" / "code" / f"peter_r{round_num}.md",
            ]
        else:
            targets = [
                project_root / ".take_root" / "test" / f"amy_r{round_num}.md",
                project_root / ".take_root" / "test" / f"ruby_fix_r{round_num}.md",
            ]
        for path in targets:
            if path.exists():
                print(f"\n===== {path} =====")
                print(path.read_text(encoding="utf-8"))
        return 0
    for path in files:
        print(path)
    return 0


def _cmd_resume(project_root: Path, args: argparse.Namespace) -> int:
    del args
    state = reconcile_state_from_disk(project_root)
    current = str(state.get("current_phase", "plan"))
    if current == "done":
        info("当前流程已完成，无需 resume")
        return 0
    if current == "plan":
        run_plan(project_root=project_root, reference_files=[], no_brainstorm=False, max_rounds=5)
    elif current == "code":
        run_code(project_root=project_root, plan_file=None, max_rounds=5, vcs_mode="auto")
    elif current == "test":
        run_test(project_root=project_root, max_iterations=5, escalate="auto")
    else:
        raise TakeRootError(f"未知 current_phase: {current}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = _project_root(str(args.project) if args.project else None)
    _setup_logging(bool(args.verbose), args.log_file.resolve() if args.log_file else None)
    try:
        if args.command == "init":
            run_init(project_root, refresh=bool(args.refresh), no_gitignore=bool(args.no_gitignore))
            return 0
        if args.command == "plan":
            run_plan(
                project_root=project_root,
                reference_files=[path.resolve() for path in args.reference],
                no_brainstorm=bool(args.no_brainstorm),
                max_rounds=int(args.max_rounds),
            )
            return 0
        if args.command == "code":
            run_code(
                project_root=project_root,
                plan_file=args.plan.resolve() if args.plan else None,
                max_rounds=int(args.max_rounds),
                vcs_mode=str(args.vcs),
            )
            return 0
        if args.command == "test":
            run_test(
                project_root=project_root,
                max_iterations=int(args.max_iterations),
                escalate=str(args.escalate),
            )
            return 0
        if args.command == "run":
            state = load_or_create_state(project_root)
            if not bool(state["phases"]["init"]["done"]):
                run_init(project_root)
            for phase in [item.strip() for item in str(args.phases).split(",") if item.strip()]:
                phase_args = argparse.Namespace(**vars(args))
                _run_phase(phase, project_root, phase_args)
                if not _should_continue(bool(args.no_checkpoint)):
                    return 0
            return 0
        if args.command == "status":
            state = reconcile_state_from_disk(project_root)
            print_status(state, project_root)
            return 0
        if args.command == "resume":
            return _cmd_resume(project_root, args)
        if args.command == "logs":
            return _cmd_logs(project_root, args.phase, args.round)
        raise TakeRootError(f"未知子命令: {args.command}")
    except UserAbort as exc:
        error(str(exc))
        return 2
    except RuntimeCallError as exc:
        error(str(exc))
        if args.verbose:
            raise
        return 3
    except ArtifactError as exc:
        error(str(exc))
        if args.verbose:
            raise
        return 4
    except TakeRootError as exc:
        error(str(exc))
        if args.verbose:
            raise
        return 1
