# OP-2：12h 专门稳定性记录改为可选

政策修订：`2026-10-03.op02`。只调整流程的稳定性门禁，不降低真实环境预检、Harbor 双镜像评分或双轨有效时长要求。

## 依据及适用边界

- 教程 AR-010（`T:PCA-20260929:L70–72,324`）仍保留容器稳定存活至少 12h 的目标。
- 用户通知 `U-20261003-03` 明确要求取消专门 12h 检查的流程门禁；本项按批准的 OP-2 计划实现，不宣称项目方删除了教程条文。
- 规则原文、catalog 和来源 manifest 不改；manifest 中 `workflow_revision=2026-10-03.op01` 表示那次规则快照，当前执行政策修订由任务 `workflow_policy.revision` 表达。避免仅为工程状态更新而使所有历史证据的来源锁失效。通知中“OP-0 仅记录”的句子是当时实施状态，不是现在仍未实施的声明。
- 流程版本仍 0.2.0、任务 schema 仍 1；本工作树增量未重新打迁移发布包，旧发布证据不代替本次验收。

## 新任务的行为

新初始化任务 `require_stability_receipt=false`：

1. 阶段 2 不强制安排专门浸泡；环境/工具能启动及真实 Harbor 自验照常进行。
2. 阶段4无须等待12h，仍核双路真实预检和预算；默认各自10h，后续OP-3的合格7h例外见 [时长政策](OP03_DURATION.md)。
3. 阶段 6.5 的模板不再要求 `checks.stability`。缺少时程序记 `{"status":"not_run","required":false}`，不制造通过记录。
4. 主动提交 `checks.stability` 时仍严格核镜像、至少 43200 秒、起止时间、无 OOM/异常退出、证据哈希与包内边界；已有真实证据不删除。已知环境故障不能以“诊断可选”隐去，须修复并定点复核。

真实迭代健康日志可以支持实际使用结论；10h不等于12h，也不能将两条时长相加。OOM、磁盘/FD、工具权限等异常仍记录和扣除。后续OP-3已支持有证据的7h例外；OP-4的TUI尚未启用。

## 旧任务：只读兼容与显式升级

缺 `workflow_policy` 的旧任务、`2026-10-03.op01` 任务均保留原要求，不自动写状态。

```bash
python3 "$FLOW_ROOT/cli.py" --format json task policy --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json task upgrade --task-root "$TASK_ROOT" --adopt-policy
# 审查 policy_changes、affected_stages 后，在授权范围内应用：
python3 "$FLOW_ROOT/cli.py" task upgrade --task-root "$TASK_ROOT" --adopt-policy --apply
```

- OP-01 → OP-02：仅政策修订号和稳定性字段变化时，重开阶段 6 的已通过步骤，不重开阶段 1–5；允许 runtime 已准备，因为不改模型、计时、运行模式或配置。历史日志、实验和轨迹均保留。
- 更旧、没有 Git 政策的任务：采用最新政策还会引入 OP-1 Git 门禁，预览会列出阶段 1；runtime 已准备时仍拒绝这类全政策切换。本次不静默迁移，也不删除 runtime 绕过。
- 若同时有真实规则来源变化，仍按原升级机制累加受影响阶段。
- 未做诊断的最新政策任务不需要创建 `stability.json`；也不要给 `checks.stability` 填空对象或 null，请省略该键。

## 可选诊断

使用 [原记录模板](templates/stability.example.json)，只填写真实观察。命令及证据根说明见 [PCA 环境说明](PCA_ENVIRONMENT.md)。`environment verify-stability` 只读检查已有记录，不启动、等待或停止容器，不修改任何证据。

薄 Skill 沿统一入口读取上述政策，本轮检查未发现其中存在额外“先等待浸泡结束”的指令，因而无需修改 Skill。
