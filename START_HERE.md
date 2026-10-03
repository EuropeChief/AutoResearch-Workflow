# AutoResearch 新流程：会话入口

状态：`0.3.0` 开发版，尚未完成发布验收。新任务仍须通过适用的镜像、GPU、provider 和两组真实预检；工具合同测试不替代正式轨迹或项目方 Hidden 验收。见 [发布状态](RELEASE.md)、[双镜像接口](PCA_ENVIRONMENT.md) 和 [部署说明](DEPLOYMENT.md)。

本入口用于执行**新流程**的专家 Agent，宿主可以是 Codex 或 Pi。用户须明确给出流程包路径与题目根目录。已有 `.autoresearch/` 的题目仍用旧流程；不静默迁移。维护流程程序本身时无需初始化一个标注题目。

教程、附件及两个完整 QA Skill 均在本流程仓内；不需要设计仓库、仓库外中央资料或历史同步报告。只支持新任务与同版本恢复；旧状态只读拒绝，使用其原版本，不迁移或手改版本号。见 [运行边界](DECOUPLING.md)。

## 每次开始或恢复

1. 确认用户给出的题目目录和授权范围。缺少目录时询问；已有授权不重复索取，不从邻近题目推断目标。
2. 阅读本文件，运行以下只读命令。`FLOW_ROOT` 指本文件所在目录，`TASK_ROOT` 指用户指定的题目目录。

```bash
python3 "$FLOW_ROOT/cli.py" --format json rules check
python3 "$FLOW_ROOT/cli.py" --format json task check --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

3. 以输出的 `current_stage`、`next_step`、证据/来源漂移及待补跨方法项目恢复工作；阅读 [六阶段操作说明](SIX_STAGES.md) 中当前阶段和所指模块文档。`stage status` 不写状态，也不发起训练或模型调用。
4. 用 `rules show --step <当前子步骤>` 查看相关规则、提前采证提示和原文位置，必要时用 `rules show --id AR-024` 定位单项。条件项标为 `requires_review` 时须判断适用性，不能默认跳过。权威顺序为当期锁定专家教程 → 项目方质检 Skill；用户明确通知仅按记录范围作为例外。规则提炼不替代原文，争议回查 `rules/manifest.json` 锁定的本仓原件；无需复制到题目目录。
5. 在已有授权和预算内推进当前子步骤；可先用 `stage check --step` 只读查看现有检查结果。真实执行并完成实质审查后用 `stage record` 登记证据；阶段退出用 `stage finish` 自动重核，记录结论和必要确认，不重复抄教程章节。遇到歧义/遗漏仍须回查原文。不要直接改 `state.json`。接口见 [状态与证据](STAGE_STATE.md)。
6. 交接时说明当前步骤、实际完成项、缺证/异常和下一条命令；确保这些信息已落在任务文件中。终端会话或聊天记忆不替代状态与原始证据。

若阶段已全部完成，继续核查证据/当前包是否变化、是否有平台反馈；`current_stage=null` 只表示专家本地阶段完成。

## 新题初始化

用户指定任务目录并授权使用新流程后：

```bash
python3 "$FLOW_ROOT/cli.py" task init --task-root "$TASK_ROOT" --task-id <实际ID> --confirm-init
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

目录须已存在。首先准备论文、题目卡、代码或明确的获取链接；环境、证据及提交包由后续阶段生成。规则来源无需重新让用户手填，先读中央 manifest；只有缺失或变更时再处理。

新任务在 1.1 完成前须执行 `task git-status`，按 [Git 操作](OP01_POLICY_GIT.md) 确认范围、建立/复用仓库、审查清单并建立初始检查点。`task init` 不替用户提交文件，也不修改 Git 身份。政策随新任务冻结，不用手改状态绕过检查。

## 按需阅读

| 当前需要 | 入口 |
|---|---|
| 顺序、交付物、冻结与回退 | [SIX_STAGES.md](SIX_STAGES.md) |
| 登记结论、引用证据、阶段冻结、返修、接续 | [STAGE_STATE.md](STAGE_STATE.md) |
| 题目自身要实现什么、可复用程序负责什么 | [TASK_ADAPTER.md](TASK_ADAPTER.md) |
| 正式协议、B/R 统计和评分 | [W2_EXPERIMENTS.md](W2_EXPERIMENTS.md) |
| 两组 Codex 模型配置、预检、启动、恢复、日志 | [W3_RUNTIME.md](W3_RUNTIME.md) |
| 阶段4.1启动前评估7h资格，结束后闭环与干净重跑验收 | [OP03_DURATION.md](OP03_DURATION.md) |
| Agent 自写轨迹整理、唯一方法、组包及独立 QA | [W4_DELIVERY.md](W4_DELIVERY.md) |
| 失败与返修处理 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

只读取当前阶段所需说明；专家 Agent 依据真实证据开展探索与实质审查，用户在既有关键节点审阅并决定是否冻结。自动检查不认证科学判断。最终 QA 由用户到新会话手动运行，取证范围限最终提交包，当前构建会话负责审阅报告、返修和重包。

## QA v0.3.1 同步

当前 QA 来源为 v0.3.1（2026-09-30），没有沿用旧口头豁免；QA15 仅因当前 Skill 原文固定跳过。静态 QA 对无材料的 H05/H06 标为不适用、运行状态 not_run，不能代替教程要求的真实 Harbor 自验。具体以 `rules show` 和本仓锁定原文为准。
