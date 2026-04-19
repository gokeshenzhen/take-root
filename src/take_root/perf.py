from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from take_root.artifacts import ensure_layout
from take_root.frontmatter import read_frontmatter_file, write_frontmatter_file
from take_root.state import take_root_dir, utc_now_iso


class PhaseTimer:
    """Collect harness-side timings for one persona call."""

    def __init__(self) -> None:
        self.breakdown_ms: dict[str, int] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self.breakdown_ms[name] = self.breakdown_ms.get(name, 0) + elapsed_ms


def aggregate_runtime_timings(runtime_timings: list[dict[str, int]]) -> dict[str, int]:
    if not runtime_timings:
        return {}
    retry_backoff_ms = 0
    totals = {
        "setup_ms": 0,
        "subprocess_ms": 0,
        "teardown_ms": 0,
        "retry_backoff_ms": 0,
    }
    for timing in runtime_timings:
        totals["setup_ms"] += timing.get("setup_ms", 0)
        totals["subprocess_ms"] += timing.get("subprocess_ms", 0)
        totals["teardown_ms"] += timing.get("teardown_ms", 0)
        retry_backoff_ms = max(retry_backoff_ms, timing.get("retry_backoff_ms", 0))
    totals["retry_backoff_ms"] = retry_backoff_ms
    return totals


def compose_timings(
    *,
    wall_sec: float,
    runtime_timings: dict[str, int],
    phase_breakdown_ms: dict[str, int],
) -> dict[str, Any]:
    llm_sec = runtime_timings.get("subprocess_ms", 0) / 1000.0
    harness_sec = max(0.0, wall_sec - llm_sec)
    harness_overhead_pct = 0.0 if wall_sec <= 0 else (harness_sec / wall_sec) * 100.0
    breakdown = dict(phase_breakdown_ms)
    breakdown["runtime_setup_ms"] = runtime_timings.get("setup_ms", 0)
    breakdown["runtime_teardown_ms"] = runtime_timings.get("teardown_ms", 0)
    breakdown["retry_backoff_ms"] = runtime_timings.get("retry_backoff_ms", 0)
    return {
        "wall_sec": round(wall_sec, 1),
        "llm_sec": round(llm_sec, 1),
        "harness_sec": round(harness_sec, 1),
        "harness_overhead_pct": round(harness_overhead_pct, 1),
        "breakdown": breakdown,
    }


def inject_timings_into_artifact(artifact_path: Path, timings: dict[str, Any]) -> None:
    parsed = read_frontmatter_file(artifact_path)
    parsed.metadata["timings"] = timings
    write_frontmatter_file(artifact_path, parsed.metadata, parsed.body)


def append_perf_record(project_root: Path, phase: str, record: dict[str, Any]) -> None:
    ensure_layout(project_root)
    perf_dir = take_root_dir(project_root) / "perf"
    perf_dir.mkdir(parents=True, exist_ok=True)
    target = perf_dir / f"{phase}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def build_perf_record(
    *,
    phase: str,
    round_num: int,
    persona: str,
    runtime: str,
    model: str,
    effort: str | None,
    artifact: str,
    timings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ts": utc_now_iso(),
        "phase": phase,
        "round": round_num,
        "persona": persona,
        "runtime": runtime,
        "model": model,
        "effort": effort,
        "wall_sec": timings["wall_sec"],
        "llm_sec": timings["llm_sec"],
        "harness_sec": timings["harness_sec"],
        "harness_overhead_pct": timings["harness_overhead_pct"],
        "artifact": artifact,
        "breakdown": timings["breakdown"],
    }
