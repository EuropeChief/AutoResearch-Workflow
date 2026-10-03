# AutoResearch 新流程：会话入口

状态：`0.2.0` PCA 版已发布。Harbor 0.23.0 有限适配、真实候选移交/独立评分、Seed 原会话短联调及异路径迁移验收已完成。每道新题仍必须通过本机镜像、GPU、provider 和两组真实预检；工具发布不替代正式 10h 轨迹或项目方 Hidden 验收。见 [发布状态](RELEASE.md)、[双镜像接口](PCA_ENVIRONMENT.md) 和 [部署说明](DEPLOYMENT.md)。

本入口用于执行**新流程**的专家 Agent，宿主可以是 Codex 或 Pi。用户须明确给出流程包路径与题目根目录。已有 `.autoresearch/` 的题目仍用旧流程；不静默迁移。维护流程程序本身时无需初始化一个标注题目。

`2026-10-03.decoupled` 修订已将设计资料与运行依赖分开。新题不需要设计仓库；教程和 QA skills 仍集中提供。已有题目因来源锁路径变化须先预览显式升级，见 [解耦与兼容](DECOUPLING.md)。不要把来源路径迁移当作规则变更而要求重跑轨迹。

工作树增量：OP-0/1 已加入 Git 与冻结政策，OP-2 将专门 12h 稳定性收据改为可选；`2026-10-03.op03` 接入启动前冻结的非训练 7h 例外，默认仍为每轨 10h、exec_json。OP-4—OP-8 尚未实施。旧发布/迁移验收不能代替增量验证，见 [Git 操作](OP01_POLICY_GIT.md)、[稳定性政策](OP02_STABILITY.md)、[时长与7h例外](OP03_DURATION.md)。

## 每次开始或恢复

1. 确认用户给出的题目目录和授权范围。缺少目录时询问；已有授权不重复索取，不从邻近题目推断目标。
2. 阅读本文件，运行以下只读命令。`FLOW_ROOT` 指本文件所在目录，`TASK_ROOT` 指用户指定的题目目录。

```bash
python3 "$FLOW_ROOT/cli.py" --format json rules check
python3 "$FLOW_ROOT/cli.py" --format json task check --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

3. 以输出的 `current_stage`、`next_step`、证据/来源漂移及待补跨方法项目恢复工作；阅读 [六阶段操作说明](SIX_STAGES.md) 中当前阶段和所指模块文档。`stage status` 不写状态，也不发起训练或模型调用。
4. 沿当前阶段 `rule_ids` 阅读中央 `rules/catalog.json` 对应规则和原文定位。权威顺序为：当期锁定专家教程 → 项目方质检 Skill 的要求；用户明确通知仅按记录范围作为例外。规则提炼不替代原文，争议回查原文；当前 `rules/manifest.json` 提供正式来源路径、版本、适用范围和哈希，通用原件留在中央，不复制到题目目录。
5. 在已有授权和预算内推进当前子步骤。真实执行后用 `stage record` 登记证据；阶段退出前用 `stage finish` 记录教程核对、专家结论及既有用户确认。不要直接改 `state.json`。接口见 [状态与证据](STAGE_STATE.md)。
6. 交接时说明当前步骤、实际完成项、缺证/异常和下一条命令；确保这些信息已落在任务文件中。终端会话或聊天记忆不替代状态与原始证据。

若阶段已全部完成，继续核查证据/当前包是否变化、是否有平台反馈；`current_stage=null` 只表示专家本地阶段完成。

## 新题初始化

用户指定任务目录并授权使用新流程后：

```bash
python3 "$FLOW_ROOT/cli.py" task init --task-root "$TASK_ROOT" --task-id <实际ID> --confirm-init
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

目录须已存在。首先准备论文、题目卡、代码或明确的获取链接；环境、证据及提交包由后续阶段生成。规则来源无需重新让用户手填，先读中央 manifest；只有缺失或变更时再处理。

新任务在 1.1 完成前须执行 `task git-status`，按 [Git 操作](OP01_POLICY_GIT.md) 确认范围、建立/复用仓库、审查清单并建立初始检查点。`task init` 不替用户提交文件，也不修改 Git 身份。旧任务缺少 `workflow_policy` 时保留旧语义；是否显式采用新政策用 `task upgrade --adopt-policy` 预览，不手改状态。

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

只读取当前阶段所需说明；题目科学探索仍由专家完成。最终 QA 由用户到新会话手动运行，取证范围限最终提交包，当前构建会话负责审阅报告、返修和重包。

## QA v0.3.1 同步

当前 QA 来源锁定 v0.3.1（2026-09-30）。按用户本次通知，先前对 QA 项的口头豁免全部撤销；QA06/09/10/17 正常检查，QA15 仅因当前 Skill 原文固定跳过。教程仍是第一权威。静态 QA 可对无材料的 H05/H06 写不适用、运行状态 not_run，但这不能关闭教程要求的真实 Harbor 自验。规则与阶段变更见 [同步说明](QA_V031_ALIGNMENT.md)。已有任务先预览 `task upgrade`，审查后显式 `--apply`；不会自动重跑实验或改写旧轨迹。
