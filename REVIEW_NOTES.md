# REVIEW_NOTES

## (a) SPEC-GAPs filled

- `personas/jeff.md` frontmatter uses `output_artifact` (singular), while spec requires `output_artifacts` (list).  
  处理：`persona.py` 兼容两种写法，并在代码中标注 `# SPEC-GAP`.
- `SnapshotVCS.pre_round(round_num)` 接口没有传入“本轮将改动哪些文件”，无法严格做到“改前逐文件快照”。  
  处理：v1 在 `post_round` 对 `files_changed` 做快照复制，并在 `vcs.py` 标注 `# SPEC-GAP`.
- Claude `reasoning=minimal` 与本机 `claude --effort` 枚举不一致（仅 low/medium/high/max）。  
  处理：映射 `minimal -> low`，并在 `claude.py` 标注 `# SPEC-GAP`.

## (b) Runtime CLI discrepancies and adjustments

- Claude CLI (`2.1.105`)：
  - 可用：`-p`, `--append-system-prompt`, `--model`, `--effort`
  - 调整后调用：
    - 非交互：`claude -p "<boot>" --append-system-prompt "<sys>" --model <model> [--effort ...]`
    - 交互：`claude "<boot>" --append-system-prompt "<sys>" --model <model> [--effort ...]`
- Codex CLI (`0.120.0`)：
  - 无 `--reasoning` 和 `--system-prompt` 直参
  - 调整后调用：
    - `codex exec --skip-git-repo-check -m <model> -c developer_instructions="<sys>" [-c model_reasoning_effort="<effort>"] "<boot>"`
- 详细记录已写入：
  - `src/take_root/runtimes/claude.NOTES.md`
  - `src/take_root/runtimes/codex.NOTES.md`

## (c) Spec-author double-check items

- `init` 阶段当前实现为“Claude 返回 CLAUDE.md 内容，由 harness 写入文件”，而非“Claude 直接写文件”。语义等价，但执行形态略有差异。
- `run` 和 `resume` 的默认参数策略采用保守默认值（plan/code/test 各自默认轮数），未从历史命令行完整回放用户当时参数。
- `SnapshotVCS` 因接口约束在 round 后快照，若需要严格 round 前逐文件快照，应扩展 `pre_round` 入参（例如传本轮目标文件集）。
- `ruff` 配置中放行了 `RUF001`（中文全角字符）与 `N818`（`UserAbort` 命名）以符合规范文案与异常命名约束。
