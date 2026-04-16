# take-root

`take-root` 是一个 Python CLI harness，用 6 个 persona（Jeff/Robin/Jack/Ruby/Peter/Amy）把想法推进到计划、实现和测试闭环。

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

## 常用子命令

- `take-root plan --reference <file>`: 仅执行方案阶段
- `take-root code --vcs auto`: 仅执行编码阶段
- `take-root test --max-iterations 5`: 仅执行测试阶段
- `take-root resume`: 从 `.take_root/state.json` 继续
- `take-root reset`: 回退到 plan 起点，清空 workflow 工件并先备份到 `.take_root/trash/<timestamp>/`
- `take-root reset --to code|test`: 仅回退指定阶段及后续阶段，保留前置产物
- `take-root reset --all`: 彻底清空配置与上下文，也会先备份到 `.take_root/trash/<timestamp>/`
- `take-root logs [plan|code|test] --round N`: 查看各轮 artifact

## 开发验证

```bash
pytest
python3.11 -m mypy --strict src/take_root
ruff check .
ruff format --check .
```
