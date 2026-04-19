from __future__ import annotations

import os
import time
from pathlib import Path

from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimePolicy

_FIXTURE_ENV = "TAKE_ROOT_FAKE_FIXTURE_DIR"
_DELAY_ENV = "TAKE_ROOT_FAKE_DELAY_MS"


class FakeRuntime(BaseRuntime):
    """Zero-network runtime used by tests and benchmarks."""

    @classmethod
    def check_available(cls) -> None:
        return

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeCallResult:
        del cwd, timeout_sec
        output_path = policy.output_path if policy is not None else None
        if output_path is None:
            output_path = _boot_output_path(boot_message)
        if output_path is None:
            raise RuntimeError("FakeRuntime requires output_path in policy or boot_message")
        return self._write_fixture(boot_message, output_path)

    def call_interactive(self, boot_message: str, cwd: Path) -> RuntimeCallResult:
        del boot_message
        output_path = cwd / ".take_root" / "plan" / "jeff_proposal.md"
        return self._write_fixture("", output_path)

    def _write_fixture(self, boot_message: str, output_path: Path) -> RuntimeCallResult:
        delay_ms = int(os.getenv(_DELAY_ENV, "5"))
        started = time.monotonic()
        time.sleep(delay_ms / 1000.0)
        fixture = self._resolve_fixture(boot_message)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(fixture, encoding="utf-8")
        duration = time.monotonic() - started
        return RuntimeCallResult(
            exit_code=0,
            stdout="",
            stderr="",
            duration_sec=duration,
            timings={
                "setup_ms": 0,
                "subprocess_ms": int(duration * 1000),
                "teardown_ms": 0,
                "retry_backoff_ms": 0,
            },
        )

    def _resolve_fixture(self, boot_message: str) -> str:
        base = _fixture_dir()
        name = self.persona.name
        mode = _sniff_field(boot_message, "mode")
        candidates = _fixture_candidates(name, mode)
        for candidate_name in candidates:
            candidate = base / candidate_name
            if candidate.exists():
                content = candidate.read_text(encoding="utf-8")
                return _fill_placeholders(content, boot_message)
        raise RuntimeError(f"FakeRuntime: no fixture for persona={name} mode={mode} in {base}")


def _fixture_dir() -> Path:
    value = os.getenv(_FIXTURE_ENV)
    if value:
        return Path(value)
    here = Path(__file__).resolve().parents[3]
    return here / "tests" / "fixtures" / "artifacts"


def _fixture_candidates(persona_name: str, mode: str | None) -> list[str]:
    if persona_name == "jeff":
        return ["jeff.md"]
    if persona_name == "robin" and mode == "finalize":
        return ["robin_finalize.md", "robin.md"]
    if persona_name == "robin":
        return ["robin_review_round.md", "robin.md"]
    if persona_name == "neo":
        return ["neo_review_round.md", "neo.md"]
    if persona_name == "lucy" and mode == "fix":
        return ["lucy_fix.md", "lucy.md"]
    if persona_name == "lucy":
        return ["lucy_implement.md", "lucy.md"]
    if persona_name == "peter":
        return ["peter_review_round.md", "peter.md"]
    if persona_name == "amy":
        return ["amy.md"]
    return [f"{persona_name}.md"]


def _fill_placeholders(content: str, boot_message: str) -> str:
    replacements = {
        "{{round}}": _sniff_field(boot_message, "round") or "1",
        "{{iteration}}": _sniff_field(boot_message, "iteration") or "1",
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content


def _sniff_field(boot_message: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in boot_message.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return None


def _boot_output_path(boot_message: str) -> Path | None:
    value = _sniff_field(boot_message, "output_path")
    if not value:
        return None
    return Path(value)
