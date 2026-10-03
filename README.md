# AutoResearch 标注流程

面向新任务的 Agent 驱动流程：专家 Agent 处理题目研究和流程执行，用户在关键节点确认科学结论与授权。当前为 **0.3.0 开发版，尚未完成发布验收**；实际状态见 [RELEASE.md](RELEASE.md)。

从 [START_HERE.md](START_HERE.md) 开始。运行仓库已自包含教程及两个完整项目方 QA Skill，不依赖设计仓库或原机器的中央资料目录。新环境准备见 [DEPLOYMENT.md](DEPLOYMENT.md)。

在本目录执行：

```bash
python3 cli.py --format json rules check
python3 cli.py --format json rules show --step 2.3
python3 cli.py --format json task init --task-root /已存在的题目目录 --task-id example-001 --confirm-init
python3 cli.py --format json stage status --task-root /已存在的题目目录
```

所有题目命令明确指定目录；不推断目标、不静默初始化。当前版本只支持新任务和同版本恢复，旧状态只读拒绝，请用其原版本处理；不提供迁移命令。

## 按需入口

| 需要 | 文档 |
|---|---|
| 六阶段、关键确认和返修 | [阶段说明](SIX_STAGES.md)、[状态与证据](STAGE_STATE.md) |
| 题目实现与通用程序的边界 | [题目适配](TASK_ADAPTER.md) |
| 实验、统计、Baseline 和评分 | [实验与评分](W2_EXPERIMENTS.md) |
| 双路 Codex 配置、运行、原始日志和恢复 | [运行底座](W3_RUNTIME.md) |
| Agent 自写轨迹、唯一方法、提交包及独立 QA | [证据和交付](W4_DELIVERY.md) |
| Git、运行时长和可选稳定性诊断 | [Git](OP01_POLICY_GIT.md)、[时长](OP03_DURATION.md)、[稳定性](OP02_STABILITY.md) |
| 错误处理 | [故障处理](TROUBLESHOOTING.md) |

## 合同与边界

- 规则全文定义在 `rules/catalog.json`，`rules show --id AR-024` 或 `--step 2.3` 展示相关要求、时机和原文位置。当前含 50 条规则和 38 项 QA 映射；需判断适用性的规则不会自动跳过。
- `rules/manifest.json` 锁定本仓教程、QA 原件及附件哈希；争议按当期教程、QA 要求顺序回查，明确用户通知仅在其范围内作为例外。
- 题目状态保存在 `.autoresearch-flow/`，包括协议、来源锁、证据及阶段记录。程序核验结构与事实，不认证科学判断；原始日志不能替代 Agent 自写轨迹。
- 最终 QA 由用户在独立新会话运行，只以整理好的最终提交包为证据范围。
- 本仓合同测试不代表真实模型、GPU、长程轨迹或项目方验收通过；不自动安装宿主依赖、使用账号或启动付费作业。

维护者离线回归：

```bash
python3 -m unittest discover -s tests -q
python3 cli.py --format json rules check
```
