---
artifact: final_plan
version: 1
project_root: /tmp/project
based_on: jeff_proposal.md
negotiation_rounds: 2
converged: false
created_at: 2026-04-19T00:00:00Z
---
# 最终方案：Harness Benchmark Baseline

## 1. 目标
- 建立性能测量基线。

## 2. 非目标
- 不修改并发模型。

## 3. 背景与约束
- 需要区分 LLM 时间与 harness 开销。

## 4. 设计概览
- 增加 FakeRuntime、计时与 JSONL。

## 5. 关键决策
- 使用前端摘要和工件 frontmatter 承载 timings。

## 6. 实施步骤
- 实现 runtime 注入。
- 注入 phase 级 timing。
- 增加 benchmark 测试。

## 7. 验收标准
- 产出 perf JSONL 与带 timings 的 artifact。

## 8. 已知风险与未决问题
- 基线结果依赖工作区大小。
