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
- `take-root logs [plan|code|test] --round N`: 查看各轮 artifact

## 开发验证

```bash
pytest
python3.11 -m mypy --strict src/take_root
ruff check .
ruff format --check .
```
