from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from take_root.errors import PolicyError

_SUSPICIOUS_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?i)\b(ignore|bypass|override|disregard|redefine)\b.{0,40}\b("
            r"system|developer|safety|permission|tool)\b"
        ),
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"(?i)\b(exfiltrat|reveal|dump|print|send|leak)\w*\b.{0,40}\b("
            r"secret|credential|token|api[_ -]?key|password|ssh[_ -]?key|private[_ -]?key)\b"
        ),
    ),
    (
        "permission_escalation",
        re.compile(
            r"(?i)(--dangerously-skip-permissions|allow-dangerously-skip-permissions|"
            r"\bgrant\b.{0,20}\b(shell|write|full)\b.{0,20}\b(access|permission)\b)"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    kind: str
    size: int
    mtime_ns: int
    sha256: str | None
    target: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    root: Path
    allowed_output_path: Path
    entries: dict[str, WorkspaceEntry]
    output_entry: WorkspaceEntry | None
    output_bytes: bytes | None

    def out_of_scope_changes(self) -> list[str]:
        current = snapshot_workspace(self.root, self.allowed_output_path)
        allowed = _relative_key(self.allowed_output_path, self.root)
        changed: list[str] = []
        for rel_path in sorted(set(self.entries) | set(current.entries)):
            if rel_path == allowed:
                continue
            before = self.entries.get(rel_path)
            after = current.entries.get(rel_path)
            if before != after:
                changed.append(rel_path)
        return changed

    def assert_only_output_changed(self) -> None:
        changed = self.out_of_scope_changes()
        if changed:
            sample = ", ".join(changed[:8])
            suffix = "" if len(changed) <= 8 else f" ... (+{len(changed) - 8} more)"
            raise PolicyError(
                f"review_only policy violation: files outside output_path changed: {sample}{suffix}"
            )

    def restore_output_path(self) -> None:
        path = self.allowed_output_path
        if self.output_entry is None:
            if path.exists() or path.is_symlink():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            path.unlink()
        if self.output_entry.kind == "symlink":
            if self.output_entry.target is None:
                raise PolicyError("cannot restore output_path symlink without saved target")
            path.symlink_to(self.output_entry.target)
            return
        if self.output_bytes is None:
            raise PolicyError("cannot restore output_path file without saved bytes")
        path.write_bytes(self.output_bytes)


def scan_review_context(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for label, pattern in _SUSPICIOUS_LINE_PATTERNS:
                if pattern.search(line):
                    raise PolicyError(
                        f"blocked suspicious review context in {path}:{lineno} ({label})"
                    )


def snapshot_workspace(project_root: Path, allowed_output_path: Path) -> WorkspaceSnapshot:
    root = project_root.resolve()
    output = allowed_output_path.resolve()
    entries: dict[str, WorkspaceEntry] = {}
    for path in _iter_workspace_paths(root):
        rel_path = _relative_key(path, root)
        entries[rel_path] = _snapshot_entry(path)
    output_entry = entries.get(_relative_key(output, root))
    output_bytes: bytes | None = None
    if output_entry is not None and output_entry.kind == "file":
        output_bytes = output.read_bytes()
    return WorkspaceSnapshot(
        root=root,
        allowed_output_path=output,
        entries=entries,
        output_entry=output_entry,
        output_bytes=output_bytes,
    )


def write_policy_violation_report(
    *,
    project_root: Path,
    persona_name: str,
    output_path: Path,
    details: str,
    changed_paths: list[str] | None = None,
) -> Path:
    report_dir = project_root / ".take_root" / "plan" / "policy_violations"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"{timestamp}_{persona_name}.json"
    payload = {
        "persona": persona_name,
        "output_path": str(output_path.resolve()),
        "details": details,
        "changed_paths": changed_paths or [],
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def _iter_workspace_paths(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if path == project_root / ".git" or (project_root / ".git") in path.parents:
            continue
        if path.is_dir():
            continue
        files.append(path)
    return sorted(files)


def _snapshot_entry(path: Path) -> WorkspaceEntry:
    stat = path.lstat()
    if path.is_symlink():
        return WorkspaceEntry(
            kind="symlink",
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            sha256=None,
            target=str(path.readlink()),
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return WorkspaceEntry(
        kind="file",
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=digest,
        target=None,
    )


def _relative_key(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path.resolve().relative_to(project_root.resolve()))
