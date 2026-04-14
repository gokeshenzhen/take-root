# Codex Runtime Invocation Notes

Verified with local CLI:

- `codex --version` -> `codex-cli 0.120.0`
- `codex exec --help` supports:
  - model selection: `-m/--model`
  - config override: `-c key=value`
  - prompt as positional argument
  - no direct `--reasoning` or `--system-prompt` flag in this version

Final invocation format used by `CodexRuntime`:

- `codex exec --skip-git-repo-check -m <persona.model> -c developer_instructions="<persona.system_prompt>" [-c model_reasoning_effort="<persona.reasoning>"] "<boot_message>"`

Rationale:

- `developer_instructions` injects persona prompt as a dedicated higher-priority instruction block.
- `model_reasoning_effort` is passed via config override because this CLI version does not expose a direct flag.
