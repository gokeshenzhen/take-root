from __future__ import annotations

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from take_root.errors import UserAbort, VCSError

LOGGER = logging.getLogger(__name__)


class VCSHandler(ABC):
    @abstractmethod
    def pre_round(self, round_num: int) -> None:
        """Prepare VCS state before a round."""

    @abstractmethod
    def post_round(
        self,
        round_num: int,
        files_changed: list[Path],
        summary: str,
        prefix: str,
    ) -> dict[str, str | None]:
        """Persist round result in selected VCS backend."""

    @abstractmethod
    def detect_dirty(self) -> bool:
        """Return true when current working tree is dirty."""


def _run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise VCSError(f"Command failed ({' '.join(cmd)}): {result.stderr.strip()}")
    return result


class GitVCS(VCSHandler):
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def _has_tracked_changes(self) -> bool:
        return _git_diff_exists(
            ["git", "diff", "--quiet", "--ignore-submodules", "--"],
            cwd=self.project_root,
        ) or _git_diff_exists(
            ["git", "diff", "--cached", "--quiet", "--ignore-submodules", "--"],
            cwd=self.project_root,
        )

    def _has_staged_changes(self) -> bool:
        return _git_diff_exists(
            ["git", "diff", "--cached", "--quiet", "--ignore-submodules", "--"],
            cwd=self.project_root,
        )

    def pre_round(self, round_num: int) -> None:
        LOGGER.debug("GitVCS pre_round %d", round_num)

    def post_round(
        self,
        round_num: int,
        files_changed: list[Path],
        summary: str,
        prefix: str,
    ) -> dict[str, str | None]:
        del round_num
        existing: list[str] = []
        for path in files_changed:
            abs_path = path if path.is_absolute() else self.project_root / path
            if abs_path.exists():
                existing.append(str(abs_path.relative_to(self.project_root)))
        if existing:
            _run(["git", "add", *existing], cwd=self.project_root)
        if not self._has_staged_changes():
            return {"commit_sha": None, "snapshot_dir": None}
        message = f"{prefix} {summary}".strip()
        _run(["git", "commit", "-m", message], cwd=self.project_root)
        head = _run(["git", "rev-parse", "HEAD"], cwd=self.project_root)
        return {"commit_sha": head.stdout.strip(), "snapshot_dir": None}

    def detect_dirty(self) -> bool:
        return self._has_tracked_changes()


class SnapshotVCS(VCSHandler):
    def __init__(self, project_root: Path, snapshot_root: Path | None = None) -> None:
        self.project_root = project_root
        self.snapshot_root = (
            snapshot_root
            if snapshot_root is not None
            else project_root / ".take_root" / "code" / "snapshots"
        )

    def pre_round(self, round_num: int) -> None:
        del round_num
        # SPEC-GAP: snapshot pre-copy needs precomputed file list from artifact;
        # v1 stores snapshot after round for known changed files.
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def post_round(
        self,
        round_num: int,
        files_changed: list[Path],
        summary: str,
        prefix: str,
    ) -> dict[str, str | None]:
        del summary, prefix
        round_dir = self.snapshot_root / f"r{round_num}"
        for rel in files_changed:
            abs_path = rel if rel.is_absolute() else self.project_root / rel
            if not abs_path.exists():
                continue
            target = round_dir / abs_path.relative_to(self.project_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, target)
        return {"commit_sha": None, "snapshot_dir": str(round_dir)}

    def detect_dirty(self) -> bool:
        return False


class OffVCS(VCSHandler):
    def pre_round(self, round_num: int) -> None:
        del round_num

    def post_round(
        self,
        round_num: int,
        files_changed: list[Path],
        summary: str,
        prefix: str,
    ) -> dict[str, str | None]:
        del round_num, files_changed, summary, prefix
        return {"commit_sha": None, "snapshot_dir": None}

    def detect_dirty(self) -> bool:
        return False


PromptFn = Callable[[str], str]


def _prompt_default(prompt: str) -> str:
    return input(prompt)


def _ensure_git_initialized(project_root: Path) -> None:
    _run(["git", "init"], cwd=project_root)
    status = _run(["git", "status", "--porcelain"], cwd=project_root)
    if status.stdout.strip():
        files = [line[3:] for line in status.stdout.splitlines() if len(line) > 3]
        if files:
            _run(["git", "add", *files], cwd=project_root)
            _run(["git", "commit", "-m", "[take-root init] bootstrap"], cwd=project_root)


def select_vcs_mode(
    project_root: Path,
    user_choice: str | None,
    prompt_fn: PromptFn = _prompt_default,
) -> VCSHandler:
    choice = (user_choice or "auto").strip().lower()
    if choice not in {"git", "snapshot", "off", "auto"}:
        raise VCSError(f"Unsupported VCS mode: {user_choice}")
    if choice == "git":
        return GitVCS(project_root)
    if choice == "snapshot":
        return SnapshotVCS(project_root)
    if choice == "off":
        return OffVCS()

    git_dir = project_root / ".git"
    if git_dir.exists():
        handler = GitVCS(project_root)
        if not handler.detect_dirty():
            return handler
        answer = (
            prompt_fn(
                "检测到当前 Git 工作区有未提交改动。请选择 [commit / stash / proceed / abort]："
            )
            .strip()
            .lower()
        )
        if answer in {"proceed", "p", ""}:
            return handler
        if answer == "abort":
            raise UserAbort("用户取消：请先处理工作区改动后再运行")
        raise UserAbort("请先手动 commit 或 stash，再重新执行")

    answer = (
        prompt_fn(
            "当前项目未启用 Git。建议开启版本管理：\n"
            "  [1] git-init   - 在当前目录 git init，并自动提交每轮 Ruby 变更\n"
            "  [2] snapshot   - 每轮将变更文件拷贝到 .take_root/code/snapshots/r{N}/\n"
            "  [3] off        - 不做版本保护，无法回滚\n"
            "  [4] abort      - 退出后你自行配置\n"
            "选择 [1]: "
        )
        .strip()
        .lower()
    )
    if answer in {"", "1", "git-init", "git"}:
        _ensure_git_initialized(project_root)
        return GitVCS(project_root)
    if answer in {"2", "snapshot"}:
        return SnapshotVCS(project_root)
    if answer in {"3", "off"}:
        return OffVCS()
    raise UserAbort("用户取消：未选择可用的 VCS 方案")


def _git_diff_exists(cmd: list[str], cwd: Path) -> bool:
    result = _run(cmd, cwd=cwd, check=False)
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise VCSError(f"Command failed ({' '.join(cmd)}): {result.stderr.strip()}")
