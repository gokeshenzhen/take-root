Now I have a comprehensive understanding. Here's the CLAUDE.md:

# CLAUDE.md — take-root harness

## Purpose

`take-root` is a Python CLI harness that orchestrates a 6-persona AI workflow (Jeff/Robin/Jack/Ruby/Peter/Amy) to turn ideas into tested implementations via multi-round negotiation between specialized agents.

## Tech Stack

- Python 3.11+ (strict type hints, `from __future__ import annotations` everywhere)
- PyYAML for frontmatter parsing
- External CLIs: `codex` (primary runtime for init/plan/code/test), `claude` (legacy supported runtime) — invoked via subprocess
- Dev: pytest + pytest-cov, mypy --strict, ruff (format + check)
- No async, no telemetry, no heavy dependencies

## Directory Layout

```
├── personas/              # 6 persona contracts (jeff, robin, jack, ruby, peter, amy)
├── plan/                  # Design docs (IMPLEMENTATION_SPEC.md, idea.md, etc.)
├── src/take_root/
│   ├── __init__.py        # Version 0.1.0
│   ├── __main__.py        # python -m take_root
│   ├── cli.py             # Argparse CLI, subcommand dispatch
│   ├── errors.py          # Exception hierarchy (7 classes)
│   ├── state.py           # JSON state machine, atomic writes
│   ├── persona.py         # Persona loader + per-project override resolution
│   ├── artifacts.py       # Path helpers for .take_root/ layout
│   ├── frontmatter.py     # YAML frontmatter parse/serialize
│   ├── ui.py              # Terminal output (info/warn/error/print_status)
│   ├── vcs.py             # GitVCS / SnapshotVCS / OffVCS
│   ├── runtimes/
│   │   ├── base.py        # BaseRuntime ABC, retry logic, RuntimeConfig
│   │   ├── claude.py      # ClaudeRuntime (legacy supported runtime)
│   │   └── codex.py       # CodexRuntime (subprocess `codex` / `codex exec`)
│   └── phases/
│       ├── __init__.py    # boot_message(), validate_artifact()
│       ├── init.py        # CLAUDE.md bootstrap via Codex
│       ├── plan.py        # Jeff → Robin ↔ Jack negotiation (≤5 rounds)
│       ├── code.py        # Ruby ↔ Peter code/review (≤5 rounds)
│       └── test.py        # Amy → Ruby-fix loop (≤N iterations)
├── tests/                 # 12 test files (unit + integration)
├── pyproject.toml         # All config (pytest, mypy, ruff)
└── README.md
```

## Commands

```bash
# Install (dev)
pip install -e .

# Run
take-root init                    # Bootstrap CLAUDE.md for target project
take-root plan [--max-rounds N]   # Planning phase
take-root code [--vcs auto|git|snapshot|off]  # Implementation phase
take-root test [--max-iterations N]           # Testing phase
take-root run [--phases plan,code,test]       # All phases sequentially
take-root status                  # Show current state
take-root resume                  # Resume from saved state
take-root logs [phase] [--round N]            # View artifacts

# Test
pytest                            # Unit tests only
PYTEST_INTEGRATION=1 pytest       # Include integration tests
pytest -v                         # Verbose

# Type check
mypy --strict src/take_root

# Lint & format
ruff check .
ruff format .
ruff format --check .
```

## Key Entrypoints

- **CLI**: `src/take_root/cli.py:main()` — argparse dispatcher
- **Phases**: `phases/init.py:run_init()`, `phases/plan.py:run_plan()`, `phases/code.py:run_code()`, `phases/test.py:run_test()`
- **Console script**: `take-root` (registered in pyproject.toml)

## Coding Conventions

- All public functions require type annotations; mypy --strict enforced
- Line length: 100 (ruff)
- Target: Python 3.11
- UTF-8 encoding explicit on all file I/O (`Path.read_text(encoding="utf-8")`)
- Subprocess: `subprocess.run(capture_output=True, text=True, check=False)` + manual returncode checks
- State writes: atomic via `.tmp` file + `os.replace()`
- Exceptions: use hierarchy from `errors.py` (TakeRootError base)
- Artifacts: markdown files with YAML frontmatter; validated via `validate_artifact()`
- Persona overrides: project-level `.take_root/personas/<name>.md` shadows harness defaults

## Architecture Notes

- **Cold-start personas**: Each phase spawns fresh subprocess calls; no in-memory state between rounds. Personas reconstruct context from prior artifact files.
- **State machine**: `.take_root/state.json` tracks phase, round, last actor. `transition()` merges updates atomically. `reconcile_state_from_disk()` rebuilds from artifacts if state is lost.
- **Boot messages**: Structured key-value format injected as system prompt; size-limited (warn at 8KB, abort at 32KB).
- **Frontmatter as contract**: Each persona's output must include specific metadata keys (e.g., Robin needs `addresses`, Jack needs `open_attacks`). Harness validates these.
- **VCS abstraction**: `VCSHandler` ABC with `pre_round()` / `post_round()` hooks. Auto-detects git; falls back to snapshot or off.

## Non-Obvious Gotchas

1. **State schema versioning**: `STATE_SCHEMA_VERSION = 1` in `state.py`. Mismatches raise `StateError`. Must plan migrations if bumping.
2. **Harness root discovery**: `find_harness_root()` walks up from `__file__` looking for `personas/` dir. Fails if package is installed outside the repo tree.
3. **CLAUDE.md staleness**: `_is_claude_stale()` in `plan.py` checks file age (>7 days) and git HEAD mtime; auto-prompts refresh before planning.
4. **Retry logic**: `base.py` retries on rate-limit/connection errors detected via stderr patterns. Backoff: (10, 30) seconds.
5. **Timeout env vars**: `TAKE_ROOT_TIMEOUT_PLAN` (900s), `TAKE_ROOT_TIMEOUT_CODE` (1800s), `TAKE_ROOT_TIMEOUT_TEST` (3600s).
6. **Integration tests gated**: `@pytest.mark.integration` tests require `PYTEST_INTEGRATION=1` env var.
7. **AGENTS.md symlink**: `init` phase creates `AGENTS.md → CLAUDE.md` symlink for Codex compatibility.
8. **VCS dirty-tree prompt**: If `.git/` exists but tree is dirty, VCS auto-detection prompts user before proceeding.
9. **SPEC-GAP in code phase**: `code.py:172-174` — Ruby artifact should write `commit_sha` per spec §9.2, but harness only persists it in state.json.

## Persona Workflow

```
init:  Codex → CLAUDE.md
plan:  Jeff (Codex brainstorm) → Robin (Codex plan) ↔ Jack (Codex adversarial review) → final_plan.md
code:  Ruby (implement) ↔ Peter (code review) → committed code
test:  Amy (run tests) → Ruby (fix failures) → repeat until pass
```

## Test Structure

| File | Coverage |
|------|----------|
| `test_persona.py` | Persona loading, overrides |
| `test_frontmatter.py` | Frontmatter parsing |
| `test_vcs.py` | VCS handlers |
| `test_state.py` | State machine |
| `test_cli.py` | CLI argparse |
| `test_phases_helpers.py` | Phase helpers |
| `test_init_phase.py` | Init phase |
| `test_code_phase.py` | Code phase |
| `test_test_phase.py` | Test phase |
| `test_ui.py` | UI functions |
| `test_runtimes.py` | Runtime mocks |
| `test_integration.py` | End-to-end (gated) |
