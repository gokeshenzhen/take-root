from __future__ import annotations

import subprocess
from pathlib import Path

from take_root.errors import UserAbort
from take_root.vcs import GitVCS, OffVCS, SnapshotVCS, select_vcs_mode


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _init_git_repo(path: Path) -> None:
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "test@example.com"], cwd=path)
    _run(["git", "config", "user.name", "Take Root Test"], cwd=path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=path)
    _run(["git", "commit", "-m", "init"], cwd=path)


def test_git_vcs_commit_and_dirty_detection(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    handler = GitVCS(tmp_path)
    assert handler.detect_dirty() is False
    file_path = tmp_path / "README.md"
    file_path.write_text("changed\n", encoding="utf-8")
    assert handler.detect_dirty() is True
    result = handler.post_round(
        round_num=1,
        files_changed=[Path("README.md")],
        summary="update",
        prefix="[take-root code r1]",
    )
    assert result["commit_sha"] is not None
    assert handler.detect_dirty() is False


def test_snapshot_vcs_copies_changed_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    changed = tmp_path / "src" / "a.py"
    changed.write_text("print('x')\n", encoding="utf-8")
    handler = SnapshotVCS(tmp_path)
    result = handler.post_round(
        round_num=2,
        files_changed=[Path("src/a.py")],
        summary="snapshot",
        prefix="[take-root code r2]",
    )
    assert result["snapshot_dir"] is not None
    snapshot_file = tmp_path / ".take_root" / "code" / "snapshots" / "r2" / "src" / "a.py"
    assert snapshot_file.exists()


def test_off_vcs_noop() -> None:
    handler = OffVCS()
    result = handler.post_round(1, [], "none", "[x]")
    assert result["commit_sha"] is None
    assert handler.detect_dirty() is False


def test_select_vcs_mode_no_git_prompt_snapshot(tmp_path: Path) -> None:
    handler = select_vcs_mode(tmp_path, "auto", prompt_fn=lambda _: "2")
    assert isinstance(handler, SnapshotVCS)


def test_select_vcs_mode_abort(tmp_path: Path) -> None:
    try:
        select_vcs_mode(tmp_path, "auto", prompt_fn=lambda _: "4")
    except UserAbort:
        return
    raise AssertionError("expected UserAbort")
