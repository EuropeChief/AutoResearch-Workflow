# LP-7 入口收口与定向回归

日期：2026-10-09  
范围：流程包默认入口、发布搬迁自检、故障/运行接口说明和回归测试。没有启动模型、GPU、Docker 或真实题目，也没有修改历史题目与正式科研证据。

## 已完成

- `cli.py` 的默认帮助只展示 `materials`、`package`、`harbor`、`rules`、`environment`、`experiment` 和 `runtime` 等无状态能力；`task`、`stage`、`delivery` 以及旧实验动作仍可解析，但隐藏在默认帮助中，供历史任务兼容。
- `tools/release_check.py` 的搬迁烟测不再初始化 `task` 状态目录、读取 `stage status` 或生成 `.autoresearch-flow`；改为验证规则检查、无状态能力帮助和干净目录可迁移性。
- `README.md`、`docs/runtime.md`、`docs/troubleshooting.md` 和历史接口页明确新题的无状态路径；旧账本只作为历史兼容说明，不作为启动前置。
- 新增 `tests/test_lp7_entry.py`，覆盖默认帮助、兼容路由保留、发布烟测不初始化旧状态和默认故障文档入口。
- 设计计划已更新 LP-7 状态；LP-7T（ToB-17/ToB-24 真实适配）与 LP-8 仍是后续独立工作项。

## 验证与边界

- `python -m unittest tests.test_lp7_entry -v`：4 项通过。
- `python cli.py --help`：旧状态/交付路由不出现在默认命令列表；新能力入口可见。
- 通过 `git diff --check`，未发现空白错误。
- `python -m unittest discover -s tests -v`：462 项通过；`python tools/release_check.py` 的搬迁自检同步通过，生成的合同收据仍标为 `contracts_passed`，未宣称正式发行。
- 尚未运行正式发布命令或 LP-7T 真实题目适配；该记录不宣称 Harbor、GPU、模型或科学任务已通过。
