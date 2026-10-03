# 运行包与设计资料的边界

包修订：`2026-10-03.decoupled`。本次只解耦目录/发布依赖，不改变规则要求、评分、Agent 方法或时长政策；正式新版迁移发布并入 OP-8。

## 新环境需要什么

按 [DEPLOYMENT](DEPLOYMENT.md) 提供流程仓库、集中教程和两个完整项目方 QA skills。设计仓库仅供维护者追溯，不随当前迁移包复制，也不放进题目目录。规则快照见 [provenance](rules/provenance/README.md)；它不是新的权威来源。可复用 pilot 源码保留，构建、运行、凭据和缓存不迁移。

流程源码和设计资料分别使用独立 Git；运行仓库的解耦前基线是 `d027f3f`，设计基线是 `ca978de`。设计目录原件继续保留，没有删除、建立目录链接或改写历史。原始来源名称出现在历史快照中不等于运行时仍需要它们。

## 已有 0.2.0 任务如何切换

本次修改了 manifest 的包修订/路径和 catalog 的溯源说明字段，因此文件哈希改变，但 50 条规则、38 项覆盖和用户通知不变。`rules check` 校验当前规则包；旧任务的 `task check` 会如实报告来源锁漂移，不静默重写。

```bash
python3 "$FLOW_ROOT/cli.py" --format json rules check
python3 "$FLOW_ROOT/cli.py" --format json task check --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json task upgrade --task-root "$TASK_ROOT"
```

仅在确认预览的 `changed_rules=[]`、`changed_sources=[]`、`affected_stages=[]`、`policy_changed=false` 后，才可根据该题授权执行：

```bash
python3 "$FLOW_ROOT/cli.py" task upgrade --task-root "$TASK_ROOT" --apply
```

纯路径迁移使用现有升级机制，记录旧来源锁和升级历史，已通过阶段、当前进度和冻结政策保持不变；无需重跑训练或轨迹。**不要加 `--adopt-policy`**，它代表另一项政策变更。如果预览还有规则/来源变化，须审查该题从旧版到当前的真实差异，不能套用“只是解耦”免除检查。本次维护没有升级任何真实题目。

0.1.0 不在本次状态迁移范围，仍使用匹配的历史程序。回退优先保留旧版本独立工作树；若已显式升级题目锁，应先保留最新题目状态和证据，再按可审查备份处理，不对真实题目执行破坏性 Git 复位。

## 验收和发布

离线检查在没有设计目录和 pilot 运行原件的临时中央根执行规则检查、任务初始化、文档链接和全量测试。冻结原文快照只核哈希，其原始相对链接不视为当前导航；活动说明文件的本地链接必须有效。

详见 [发布说明](RELEASE.md)。普通离线验收、未发布预览归档、正式发布是三个不同状态。新预览只证明打包和独立运行合同，不声称真实双模型联调或最终题目 QA 通过。
