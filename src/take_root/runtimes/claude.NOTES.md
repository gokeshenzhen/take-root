# Claude Runtime Invocation Notes

Verified with local CLI:

- `claude --version` -> `2.1.105 (Claude Code)`
- `claude --help` supports:
  - non-interactive mode: `-p/--print`
  - system prompt append: `--append-system-prompt`
  - model selection: `--model`
  - reasoning level: `--effort (low|medium|high|xhigh|max)`

Final invocation formats used by `ClaudeRuntime`:

- Non-interactive:
  - `claude -p "<boot_message>" --append-system-prompt "<persona.system_prompt>" --model <persona.model> [--effort <value>]`
- Interactive:
  - `claude "<boot_message>" --append-system-prompt "<persona.system_prompt>" --model <persona.model> [--effort <value>]`

Reasoning mapping:

- `low/medium/high/xhigh/max` passthrough
