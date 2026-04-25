# 🌱 take-root

<p align="center">
  <strong>Python CLI harness：6 个 persona 协作，把想法推进到计划、实现和测试闭环</strong>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/version-0.1.0-green?style=for-the-badge" alt="Version 0.1.0">
  <img src="https://img.shields.io/badge/runtimes-claude%20%7C%20codex-orange?style=for-the-badge" alt="Runtimes">
</p>

`take-root` 是一个 Python CLI harness，用 6 个 persona（Jeff/Robin/Neo/Lucy/Peter/Amy）把想法推进到计划、实现和测试闭环。

[安装](#安装) · [最小使用](#最小使用) · [交互流程](#交互流程框图) · [协作架构](#协作架构图) · [常用子命令](#常用子命令) · [开发验证](#开发验证)

## 安装

```bash
cd /home/robin/Projects/take_root
python3.11 -m pip install -e .
```

## 最小使用

```bash
cd /path/to/your/project
take-root init
take-root run
take-root status
```

## 交互流程框图

```text
+--------------------+
| 开始使用 take-root |
+---------+----------+
          |
          v
+-------------------------------+
| configure                     |
| 配置 provider / model / 路由  |
+---------+---------------------+
          |
          v
+-------------------------------+
| init                          |
| 生成 CLAUDE.md / AGENTS.md    |
+---------+---------------------+
          |
          v
+-------------------------------------------------------------------+
| run                                                                |
| 串行执行 plan -> code -> test                                      |
| phase 之间默认 checkpoint: Y / n / save-and-exit                   |
+---------+---------------------------------------------------------+
          |
          | save-and-exit
          v
+-------------------------------+         +-------------------------+
| 保存 .take_root/state.json    | ------> | resume                  |
| 并退出                        |         | 从当前 phase 继续       |
+-------------------------------+         +------------+------------+
                                                        |
                                                        v
+-------------------------------+         +-------------------------+
| plan                          | <-------+ 若 current_phase=plan   |
| Jeff 交互提案                 |         +-------------------------+
|   -> Robin review-only        |
|   -> Neo review-only         |
|   -> Robin 输出 final_plan.md |
+---------+---------------------+
          |
          v
+-------------------------------+         +-------------------------+
| code                          | <-------+ 若 current_phase=code   |
| Lucy 实现                     |         +-------------------------+
|   -> Peter review-only        |
| 循环直到 converged 或耗尽预算 |
+---------+---------------------+
          |
          v
+---------------------------------------------------+
| code 结果分叉                                     |
| 1. converged -> 进入 test                         |
| 2. exhausted_stop -> 停在 code, 给出 next_action  |
| 3. exhausted_advance -> 带风险进入 test           |
+---------+-----------------------------------------+
          |
          v
+-------------------------------+         +-------------------------+
| test                          | <-------+ 若 current_phase=test   |
| Amy 全量测试                  |         +-------------------------+
|   -> all_pass: done           |
|   -> fail: Lucy 修复后重测    |
+---------+---------------------+
          |
          v
+-------------------------------+
| done                          |
| test 全量通过，流程完成       |
+-------------------------------+
```

补充说明：

- `run` 会在 `init` 未完成时自动先跑 `init`，但不会自动补跑 `configure`。
- `plan` 的 Jeff 是交互式；Robin 和 Neo 是非交互、review-only。
- `code` 默认在预算耗尽时停在 `code`；只有显式传 `--on-code-exhausted advance` 才会进入 `test`。
- `resume` 不读取你上次传入的 CLI 调参，而是按内置默认值继续当前 phase。

## 协作架构图

```text
+------------------------------+
| 用户                         |
| 通过 take-root CLI 发起命令  |
+--------------+---------------+
               |
               v
+---------------------------------------------------------------+
| CLI 层                                                        |
| cli.py                                                        |
| configure / init / doctor / plan / code / test / run / resume |
+--------------+------------------------------------------------+
               |
               v
+---------------------------------------------------------------+
| Phase Orchestrator                                             |
| phases/configure.py                                            |
| phases/init.py                                                 |
| phases/plan.py                                                 |
| phases/code.py                                                 |
| phases/test.py                                                 |
+------+----------------------+--------------------+-------------+
       |                      |                    |
       | 读取/更新            | 生成 boot message  | 调用 runtime
       v                      v                    v
+-------------+   +---------------------------+   +--------------------+
| config.yaml |   | persona/frontmatter       |   | runtimes/          |
| provider    |   | 载入 persona 定义与约束   |   | claude.py          |
| / model 路由|   +---------------------------+   | codex.py           |
+------+------+                                   +---------+----------+
       |                                                    |
       |                                                    v
       |                                  +----------------------------------+
       |                                  | 外部模型/CLI                      |
       |                                  | Claude / Codex / 兼容 provider   |
       |                                  +----------------+-----------------+
       |                                                   |
       |                                                   v
       |                             +----------------------------------------+
       |                             | Persona 协作层                         |
       |                             | init  : 项目侦察, 生成 CLAUDE.md       |
       |                             | Jeff  : 交互式提案                     |
       |                             | Robin : review/finalize                |
       |                             | Neo  : adversarial review             |
       |                             | Lucy  : implement / fix                |
       |                             | Peter : code review                    |
       |                             | Amy   : full test                      |
       |                             +----------------+-----------------------+
       |                                              |
       +----------------------------------------------+
                                                      |
                                                      v
+--------------------------------------------------------------------------------+
| 状态与工件层                                                                   |
| .take_root/state.json                                                          |
| .take_root/plan/*.md                                                           |
| .take_root/code/*.md                                                           |
| .take_root/test/*.md                                                           |
| .take_root/run_summary.md                                                      |
| CLAUDE.md / AGENTS.md                                                          |
+-----------------------------+--------------------------------------------------+
                              |
                              v
+--------------------------------------------------------------------------------+
| 约束与恢复机制                                                                 |
| state.py: reconcile_state_from_disk() 从磁盘恢复 current_phase                 |
| guardrails.py: plan review-only 快照、越界写入检测                             |
| summary.py: 生成 next_action / overview                                        |
| vcs.py: git / snapshot / off                                                   |
+--------------------------------------------------------------------------------+
```

补充说明：

- CLI 只是入口，真正编排发生在各 `phases/*.py`。
- `plan` 阶段的 Robin / Neo 通过 review-only policy 被限制只能写各自 artifact。
- 所有阶段都以磁盘工件和 `state.json` 为恢复依据，而不是依赖会话记忆。
- `run_summary.md`、`status`、`resume` 都是围绕同一份状态模型工作的。

## 常用子命令

- `take-root plan --reference <file>`: 仅执行方案阶段
- `take-root code --vcs auto --on-code-exhausted stop|advance`: 仅执行编码阶段；达到预算未收敛时默认停在 `code`，显式传 `advance` 才允许带风险前推到 `test`
- `take-root test --max-iterations 5`: 仅执行测试阶段
- `take-root run --on-code-exhausted stop|advance`: 串行执行多个阶段，并遵守同一套 code handoff 规则
- `take-root resume`: 从 `.take_root/state.json` 继续；若 `code` 处于 `exhausted_stop`，只给出下一步建议，不会自动重跑或自动前推
- `take-root reset`: 回退到 plan 起点，清空 workflow 工件并先备份到 `.take_root/trash/<timestamp>/`
- `take-root reset --to code|test`: 仅回退指定阶段及后续阶段，保留前置产物
- `take-root reset --all`: 彻底清空配置与上下文，也会先备份到 `.take_root/trash/<timestamp>/`
- `take-root logs [plan|code|test] --round N`: 查看各轮 artifact

## 运行摘要

- 每次 `plan`、`code`、`test` 成功结束后，都会覆盖写入 `.take_root/run_summary.md`
- `take-root status` 与 `run_summary.md` 共享同一个摘要视图，都会给出当前结论、停因和下一步命令

## 开发验证

```bash
pytest
python3.11 -m mypy --strict src/take_root
ruff check .
ruff format --check .
```
