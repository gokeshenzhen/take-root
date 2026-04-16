# CLAUDE.md — take-root

## Purpose

`take-root` is a Python 3.11 CLI harness for a multi-persona implementation workflow.
It drives `configure -> init -> plan -> code -> test`, persists artifacts under `.take_root/`, and resumes from disk state instead of session memory.

## Tech Stack

- Python `3.11+`
- Packaging:
  - `setuptools`
  - `wheel`
- Runtime dependency:
  - `PyYAML>=6.0.1`
- External CLIs:
  - `claude`
  - `codex`
  - `git` for `git` VCS mode or auto-selected git mode
- Dev tooling:
  - `pytest`
  - `mypy --strict`
  - `ruff check`
  - `ruff format`

## Top-Level Layout

```text
.
├── AGENTS.md -> CLAUDE.md
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── personas/
│   ├── amy.md
│   ├── jack.md
│   ├── jeff.md
│   ├── peter.md
│   ├── robin.md
│   └── ruby.md
├── plan/
│   ├── IMPLEMENTATION_HANDOFF.md
│   ├── IMPLEMENTATION_SPEC.md
│   ├── codex_invocation.md
│   ├── idea.md
│   ├── 260415/
│   ├── 260416_configure_doctor/
│   └── 260416_plan_guardrails_spec.md
├── src/take_root/
│   ├── __init__.py
│   ├── __main__.py
│   ├── artifacts.py
│   ├── cli.py
│   ├── config.py
│   ├── doctor.py
│   ├── errors.py
│   ├── frontmatter.py
│   ├── guardrails.py
│   ├── persona.py
│   ├── reset.py
│   ├── state.py
│   ├── ui.py
│   ├── vcs.py
│   ├── phases/
│   │   ├── __init__.py
│   │   ├── code.py
│   │   ├── configure.py
│   │   ├── init.py
│   │   ├── plan.py
│   │   └── test.py
│   └── runtimes/
│       ├── __init__.py
│       ├── base.py
│       ├── claude.py
│       ├── claude.NOTES.md
│       ├── codex.py
│       ├── codex.NOTES.md
│       └── base.py
└── tests/
    ├── test_cli.py
    ├── test_config.py
    ├── test_configure.py
    ├── test_doctor.py
    ├── test_frontmatter.py
    ├── test_integration.py
    ├── test_persona.py
    ├── test_phases_helpers.py
    ├── test_plan.py
    ├── test_runtimes.py
    ├── test_state.py
    ├── test_ui.py
    └── test_vcs.py
```

## Key Entrypoints

- `src/take_root/cli.py`
  - argparse entrypoint
  - defines all subcommands
  - dispatches `configure`, `init`, `doctor`, `plan`, `code`, `test`, `run`, `reset`, `status`, `resume`, `logs`
- `src/take_root/__main__.py`
  - module entry for `python -m take_root`
- `src/take_root/config.py`
  - `.take_root/config.yaml` schema and defaults
  - provider/model alias resolution
  - runtime env injection and masking helpers
- `src/take_root/state.py`
  - `.take_root/state.json` schema
  - atomic writes via temp file + `os.replace()`
  - artifact-driven reconciliation from disk
- `src/take_root/persona.py`
  - persona frontmatter loader
  - project override resolution from `.take_root/personas/`
  - harness root discovery via `personas/`
- `src/take_root/frontmatter.py`
  - strict YAML frontmatter parse/serialize
- `src/take_root/artifacts.py`
  - `.take_root/` layout helpers
  - artifact path/list helpers
- `src/take_root/doctor.py`
  - persona route diagnostics
  - optional live runtime smoke call
  - writes reports under `.take_root/doctor/`
- `src/take_root/guardrails.py`
  - plan review-only workspace snapshotting
  - suspicious prompt-context scanning
  - policy-violation reporting
- `src/take_root/reset.py`
  - workflow rollback/full reset
  - backup to `.take_root/trash/<timestamp>/`
- `src/take_root/vcs.py`
  - `GitVCS`
  - `SnapshotVCS`
  - `OffVCS`
  - VCS auto-selection and dirty-tree prompts
- `src/take_root/runtimes/base.py`
  - subprocess execution policy
  - timeout config from env
  - transient retry matching
- `src/take_root/runtimes/claude.py`
  - wraps `claude`
- `src/take_root/runtimes/codex.py`
  - wraps `codex` / `codex exec`

## Phase Entrypoints

- `src/take_root/phases/configure.py:run_configure()`
  - interactive editor for providers, init route, persona routes
  - writes `.take_root/config.yaml`
- `src/take_root/phases/init.py:run_init()`
  - requires config first
  - generates or refreshes `CLAUDE.md`
  - creates `AGENTS.md -> CLAUDE.md` symlink when possible
  - updates `.gitignore` with `.take_root/` only if project is already a git repo
- `src/take_root/phases/plan.py:run_plan()`
  - Jeff interactive proposal
  - Robin and Jack review-only non-interactive rounds
  - Robin finalizes `.take_root/plan/final_plan.md`
- `src/take_root/phases/code.py:run_code()`
  - Ruby implementation rounds
  - Peter review rounds
  - optional per-round VCS persistence
- `src/take_root/phases/test.py:run_test()`
  - Amy full-test iterations
  - Ruby fix iterations
  - exits on all-pass or iteration cap

## Shared Helpers

- `src/take_root/phases/__init__.py:format_boot_message()`
  - serializes harness boot context
  - warns above `8 KiB`
  - aborts above `32 KiB`
- `src/take_root/phases/__init__.py:validate_artifact()`
  - validates artifact existence and required frontmatter keys
  - enforces additional heading structure for `robin_review`, `jack_review`, and `final_plan`

## CLI Surface

Console script:

```bash
take-root
```

Module entry:

```bash
python -m take_root
```

Package version:

- `0.1.0`

Subcommands in `src/take_root/cli.py`:

- `take-root init [--refresh] [--no-gitignore]`
- `take-root configure [--reset] [--section providers|init|personas]`
- `take-root doctor --persona <name|all> [--no-call]`
- `take-root plan [--reference <path> ...] [--no-brainstorm] [--max-rounds N]`
- `take-root code [--plan <path>] [--max-rounds N] [--vcs git|snapshot|off|auto]`
- `take-root test [--max-iterations N] [--escalate auto|always|never]`
- `take-root run [--phases plan,code,test] [--no-checkpoint]`
- `take-root reset [--all | --to plan|code|test] [-y]`
- `take-root status`
- `take-root resume`
- `take-root logs [plan|code|test] [--round N]`

Global flags:

- `--project <path>`
- `-v`, `--verbose`
- `--log-file <path>`

## Typical Commands

Install editable package:

```bash
python3.11 -m pip install -e .
```

Recommended first-time flow:

```bash
take-root configure
take-root init
take-root run
take-root status
```

Run phases individually:

```bash
take-root plan --reference plan/idea.md
take-root code --vcs auto
take-root test --max-iterations 5
take-root resume
take-root logs plan --round 1
take-root doctor --persona ruby
take-root doctor --persona all --no-call
```

Reset / rollback:

```bash
take-root reset
take-root reset --to code
take-root reset --to test
take-root reset --all
```

Dev checks:

```bash
pytest
PYTEST_INTEGRATION=1 pytest
python3.11 -m mypy --strict src/take_root
ruff check .
ruff format --check .
```

## Artifact Layout

Workflow artifacts live under:

```text
.take_root/
├── config.yaml
├── state.json
├── personas/
├── doctor/
├── plan/
├── code/
│   └── snapshots/
├── test/
└── trash/
```

Common artifact names:

- `plan/jeff_proposal.md`
- `plan/robin_rN.md`
- `plan/jack_rN.md`
- `plan/final_plan.md`
- `plan/policy_violations/<timestamp>_<persona>.json`
- `code/ruby_rN.md`
- `code/peter_rN.md`
- `code/snapshots/rN/...`
- `test/amy_rN.md`
- `test/ruby_fix_rN.md`
- `doctor/<persona>_report.md`
- `doctor/<persona>_runtime_env.json`

Artifact conventions:

- artifacts are markdown with YAML frontmatter
- validation is strict and phase-specific
- malformed artifacts are deleted during reconciliation

## Configuration Model

Primary config file:

- `.take_root/config.yaml`

Schema version:

- `CONFIG_SCHEMA_VERSION = 1`

Top-level keys:

- `schema_version`
- `providers`
- `init`
- `personas`

Provider kinds:

- `claude_official`
- `codex_official`
- `anthropic_compatible`

Built-in providers:

- `claude_official`
- `codex_official`
- `qwen`
- `kimi`

Built-in default models:

- `claude_official`
  - `opus -> claude-opus-4-6`
  - `sonnet -> claude-sonnet-4-6`
  - `haiku -> claude-haiku-4-5-20251001`
- `codex_official`
  - `opus -> gpt-5.4`
  - `sonnet -> gpt-5.4-mini`
  - `haiku -> gpt-5.4-mini`
- `qwen`
  - `opus -> qwen3-max`
  - `sonnet -> qwen3.6-plus`
  - `haiku -> qwen3.5-flash`
- `kimi`
  - `opus/sonnet/haiku -> kimi-k2.5`

Built-in persona route defaults:

- `init -> claude_official / opus / medium`
- `jeff -> qwen / sonnet / medium`
- `robin -> qwen / opus / high`
- `jack -> kimi / sonnet / high`
- `ruby -> codex_official / opus / high`
- `peter -> codex_official / opus / high`
- `amy -> codex_official / sonnet / medium`

Model selectors may be aliases:

- `opus`
- `sonnet`
- `haiku`

Supported effort values:

- `minimal`
- `low`
- `medium`
- `high`

Anthropic-compatible env handling:

- clears inherited anthropic env vars before injection
- injects `ANTHROPIC_BASE_URL`
- injects `ANTHROPIC_AUTH_TOKEN`
- injects `ANTHROPIC_MODEL`
- injects `ANTHROPIC_DEFAULT_*_MODEL`

## State Model

State file:

- `.take_root/state.json`

Schema version:

- `STATE_SCHEMA_VERSION = 1`

Phase progression:

- initial `current_phase = plan`
- completed `plan -> code`
- completed `code -> test`
- passing `test -> done`

Recovery behavior:

- `reconcile_state_from_disk()` reconstructs progress from artifact filenames + frontmatter
- `doctor` is not a workflow phase
- malformed artifacts are removed rather than tolerated

## Runtime Behavior

General subprocess behavior:

- `capture_output=True`
- `text=True`
- `check=False`

Retry policy for non-interactive runtime calls:

- retries up to `2` times on transient failures
- transient matching includes:
  - rate limit / `429`
  - `ECONNRESET`
  - `ETIMEDOUT`
  - `EAI_AGAIN`
  - temporary/service unavailable text

Timeout env vars:

- `TAKE_ROOT_TIMEOUT_PLAN`
- `TAKE_ROOT_TIMEOUT_CODE`
- `TAKE_ROOT_TIMEOUT_TEST`

Claude wrapper:

- non-interactive uses `claude -p`
- interactive uses `claude <boot_message>`
- system prompt passed via `--append-system-prompt`
- effort mapping is lossy:
  - `minimal -> low`
- review-only mode constrains tools to read tools plus `Write(output_path)`

Codex wrapper:

- non-interactive uses `codex exec --skip-git-repo-check`
- interactive uses `codex`
- system prompt injected via `-c developer_instructions=...`
- effort injected via `-c model_reasoning_effort=...`
- review-only mode uses:
  - `--sandbox read-only`
  - `--output-last-message <output_path>`

## Coding Conventions

Derived from source and tooling:

- use `from __future__ import annotations`
- target Python `3.11`
- keep full type annotations; mypy strict mode is enabled
- Ruff line length is `100`
- file I/O uses explicit `encoding="utf-8"`
- JSON state writes are atomic via temp file + `os.replace()`
- frontmatter parsing requires:
  - opening `---`
  - closing `---`
  - top-level YAML mapping
- frontmatter serialization uses `allow_unicode=False`
- config YAML serialization uses `allow_unicode=True`
- exceptions are centralized in `errors.py`
- project-local persona overrides shadow repo defaults at `.take_root/personas/<name>.md`

## Tests Present

- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_configure.py`
- `tests/test_doctor.py`
- `tests/test_frontmatter.py`
- `tests/test_integration.py`
- `tests/test_persona.py`
- `tests/test_phases_helpers.py`
- `tests/test_plan.py`
- `tests/test_runtimes.py`
- `tests/test_state.py`
- `tests/test_ui.py`
- `tests/test_vcs.py`

## Non-Obvious Gotchas

1. `configure` is required before `init`. `run_init()` calls `require_config()`, so the README minimal flow that starts with `init` is incomplete.
2. `run` auto-runs `init` if init is not done, but it does not auto-run `configure`.
3. `AGENTS.md` is expected to be a symlink to `CLAUDE.md`. If a non-matching file already exists, init only warns.
4. `plan` may prompt for `init --refresh` first. `_is_claude_stale()` marks `CLAUDE.md` stale if it is older than 7 days or older than `.git/HEAD`.
5. Harness root discovery is repo-shape dependent. `find_harness_root()` walks upward looking for `personas/`.
6. Persona overrides are filesystem-based, not config-based. `.take_root/personas/<name>.md` silently overrides `personas/<name>.md`.
7. Persona parsing accepts legacy singular `output_artifact` because `jeff.md` still uses it.
8. Config schema and state schema are separate and both strictly validated. Both are currently version `1`.
9. Anthropic-compatible providers deliberately clear inherited anthropic env vars before injecting resolved values.
10. `kimi` is hard-restricted to `kimi-k2.5`; other resolved model names raise `ConfigError`.
11. `doctor` can perform a real runtime call unless `--no-call` is set. It writes report/env/stdout/stderr files under `.take_root/doctor/`.
12. `resume` ignores prior CLI tuning. It resumes with hardcoded defaults: plan `max_rounds=5`, code `vcs_mode=auto`, test `max_iterations=5`, `escalate=auto`.
13. Plan review rounds are enforced as review-only. Guardrails snapshot the workspace, block suspicious review context lines, and reject out-of-scope file changes.
14. Plan-phase Robin and Jack calls are non-interactive; only Jeff is interactive in plan.
15. Auto VCS on a dirty git tree is interactive. The prompt offers `commit / stash / proceed / abort`, but only `proceed` continues; `commit` and `stash` still abort and require manual action.
16. Auto VCS on a non-git project can initialize git and create a bootstrap commit automatically.
17. Snapshot VCS is post-round only. There is no pre-round baseline snapshot.
18. Code-phase Ruby artifact validation requires `commit_sha` and `snapshot_dir` keys even when the selected VCS backend returns `None`.
19. Test-phase Ruby fix artifacts also require VCS metadata keys, but `run_test()` does not call `vcs_handler.post_round()`.
20. `reconcile_state_from_disk()` rebuilds phase progress from artifact filenames plus frontmatter, not from prior intent in memory.
21. Malformed artifact files are deleted during reconciliation rather than tolerated.
22. Boot messages above `32 KiB` fail fast with `ArtifactError`; large artifact-history lists can trigger this.
23. CLI help text and many prompts are in Chinese.
24. Integration tests are opt-in via `PYTEST_INTEGRATION=1`.
25. Full reset backs up `.take_root/*`, `CLAUDE.md`, and linked `AGENTS.md`, then recreates a fresh state; phase reset preserves config and context files.
26. `logs --round N` prints known artifact filenames for that phase rather than consulting state metadata.
