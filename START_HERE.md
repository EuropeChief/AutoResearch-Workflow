# 专家 Agent 执行入口

处理新题或接续本版本题目时读本文；维护流程本身改读 [MAINTAINING.md](MAINTAINING.md)，不为维护工作初始化标注任务。专家宿主可以是 Codex 或 Pi，两条迭代轨迹都使用 Codex CLI。环境前提与发布范围见 [README](README.md)。

## 定位当前任务

用户须明确流程包和题目根路径；无法确定时询问，不从相邻题目或聊天记忆猜测。本文件所在目录为 `FLOW_ROOT`，指定题目目录为 `TASK_ROOT`，下列命令中的变量须先赋为这两个实际路径。

```bash
python3 "$FLOW_ROOT/cli.py" --format json rules check
python3 "$FLOW_ROOT/cli.py" --format json task check --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

未初始化时，只有用户已授权使用本流程才执行下列命令；目录须已存在。初始化不连带提交 Git、不启动实验或付费调用。已有状态不覆盖；不匹配版本的状态用原版本处理，不手改版本号。

```bash
python3 "$FLOW_ROOT/cli.py" task init --task-root "$TASK_ROOT" --task-id <实际ID> --confirm-init
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
```

## 按状态推进

1. 以 `current_stage`、`next_step`、证据漂移和到期项定位工作；读 [六阶段导航](docs/stages.md) 中当前阶段及其接口。新题先建立范围明确的 Git 检查点。
2. 用 `rules show --step <当前子步骤>` 获取完整相关规则、提前留证要求和原文位置。条件项 `requires_review` 要做适用性判断，不能默认跳过。
3. 在既有授权和预算内连续执行普通操作；用 `stage check --step ...` 自动核现有结果，无需逐项人工确认。优化面、Baseline 代表性等实质判断由责任 Agent 沿代码与实验审查，不能以格式通过代替。
4. 真实工作与审查完成后用 `stage record` 登记；`stage finish` 重新核证并保存结论。只在既定冻结和授权节点请用户决定；输入见 [状态接口](docs/interfaces/state.md)。不直接修改 state.json。
5. 有缺证、冲突或异常时保留事实，按 [故障与恢复](docs/troubleshooting.md) 处理；交接前把已完成项、未决项和下一动作落在任务文件中。

权威顺序为锁定专家教程 → 项目方 QA Skill；用户明确通知仅在记载范围内例外。规则提炼不是第三个权威，歧义回查 manifest 指向的本仓原件，不要求用户重复提供版本、日期或适用范围。

`current_stage=null` 只表示本地阶段关闭；仍需看当前包是否变化、是否收到平台反馈。最终 QA 由用户在独立新会话运行，当前制作会话只交接准确包路径、接收报告并返修，不越过包边界补证。
