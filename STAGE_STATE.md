# 状态与证据：统一登记和接续

此模块把 W1 状态与 W2–W4 检查结果接起来，不运行训练、调用模型或代替独立 QA。题目根下仍使用 `.autoresearch-flow/state.json` schema 1；新增的不可覆盖记录在 `.autoresearch-flow/stage_records/`。

OP-0/1 增量为新任务增加 `workflow_policy`；旧状态只读兼容，显式政策升级及 Git 命令见 [操作说明](OP01_POLICY_GIT.md)。OP-2 的12h收据可选，OP-3 支持有证据且启动前冻结的7h例外，见 [稳定性政策](OP02_STABILITY.md)、[时长政策](OP03_DURATION.md)。OP-4—OP-8 仍待实施，默认10h/exec_json不变。

## 常用命令

```bash
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json stage template --task-root "$TASK_ROOT" --step 2.5
python3 "$FLOW_ROOT/cli.py" --format json stage ref --task-root "$TASK_ROOT" --path evidence/note.md --path evidence/log.txt
python3 "$FLOW_ROOT/cli.py" stage record --task-root "$TASK_ROOT" --file "$TASK_ROOT/records/step-2.5.json"
python3 "$FLOW_ROOT/cli.py" stage finish --task-root "$TASK_ROOT" --stage 2 --file "$TASK_ROOT/records/finish-2.json"
```

`stage template` 返回 JSON 中的 `spec` 是待填写输入；保存 **spec 内容本身**，不要连 `status` 等外层一起传回。`stage ref` 为已存在的任务内文件计算实际 SHA-256，不复制、不修改证据。模板中的示例和占位符均不是验收证据。

`record` 至少含 `step/status/reviewer/summary/evidence/checks`；可加 `inputs/outputs` 引用数组。所有引用为 `{"path":"任务内相对文件","sha256":"真实64位SHA-256"}`。同一说明或原始日志可被多个子步骤引用，无需为每步复制证据文件。

记录状态为 `in_progress`、`failed`、`awaiting_evidence` 或 `passed`。前三种保留当前步骤，不提前推进；等待证据须填当前 `due_stage`。只有完成全部子步骤后才可 finish。跨阶段可暂缓的是 B03/B07 的**跨方法部分**，在阶段 2 的 `baseline_review` 中按 W2 记录；当前可判部分仍须通过，阶段 3 必须关闭。`record` 保存失败记录时以非零退出码提示；已登记事实仍保留。

## 程序检查与专家判断

| 步骤 | 自动重核的事实 |
|---|---|
| 1.1（当前政策的新任务） | Git 范围已确认且存在真实、可追溯的初始检查点；旧政策不补门禁 |
| 2.1 | 双镜像结构及真实 Harbor 最小移交/独立评分记录；结构检查不替代实跑 |
| 2.3 | W2 正式协议已锁定 |
| 2.4 / 3.2 / 5.2 | 对应角色正式 seed 完整性及 W2 统计报告 |
| 2.5 / 3.3 / 3.5 | B01–B08 完整专家审查、证据和方法/协议绑定；阶段 3 不可遗留 deferred |
| 3.4 / 3.5 | W2 评分合同、U 依据引用、数值锚点；3.5 另核绑定冻结合同的 Harbor 出分 |
| 4.1 | 当前任务 Harbor 实跑、两组真实预检、预算批准引用与冻结时长快照；7h资格须在prepare之前确认 |
| 4.4 | 各轨独立达到冻结净时长（默认10h/合格7h）、已停止、不同会话、Agent自写轨迹；7h另核至少3轮方法闭环、演进和可继续方向 |
| 5.1 / 5.3 / 5.4 | 唯一方法快照、正式复验绑定、干净快照重跑 |
| 6.1 / 6.2 | 当前最终包的格式检查 |
| 6.3 | 当前包绑定了独立 QA 原报告，报告未被改动 |
| 6.4 / 6.5 | 逐项处置覆盖报告检查项、绑定包/报告，明确不存在未解决本地项；报告未通过项不能手改成 pass |

6.5 另核最终包内 Harbor 实跑、最佳代码与实际候选清单/评分合同绑定。OP-2 政策不要求 `checks.stability`；省略时如实记为 `not_run`，提供时仍核真实 12h、镜像、无异常及包内证据。旧政策仍必填，显式升级后取消。内部记录格式与相对路径范围见 [PCA_ENVIRONMENT.md](PCA_ENVIRONMENT.md)，不是新增平台必填文件名。

其余步骤登记专家的实际判断与证据，不自动证明论文方法、Baseline 代表性、合法迭代或模型能力。`finish` 会重新检查当前阶段所有实际程序门禁，并核阶段 2/3 使用同一个正式协议，阶段 6 全部步骤对应同一包版本。

3σ–5σ 按教程允许追加正式重复后标记平台复核，不提高为统一 5σ 硬门。该情形在 3.3/3.4/3.5 的 `checks` 中增加 `statistical_review` 文件引用：文件绑定当前 `protocol_sha256`、`experiment_sha256`，含 `platform_review_required:true`、`reviewer/rationale/evidence`。程序要求 W2 有追加 seed 且两侧完整；不能用此说明覆盖负增益、<3σ、失败的 Baseline 项或非法评分。

## 冻结与确认

`finish` 输入见 [阶段结束模板](templates/stage-finish.example.json)。每个阶段须记录锁定教程的 `sha256`、实际阅读章节 `sections`、遗漏/差异 `findings` 及处理 `resolution`。章节建议由 `stage status` 返回，不以章节号替代实际阅读。

阶段 1、2、3、6 的结束记录须引用用户确认；4.1 须引用双轨预算批准。确认文件形状见 [确认模板](templates/confirmation.example.json)，真实确认后将 `approved` 填为 `true`，`scope` 分别为 `stage-1/2/3/6` 或 `stage-4-start`。引用既有用户明确指示即可，不需要每条命令重复询问。不得把专家自己的建议写成用户已批准。

审批引用只记录来源与范围；工具不会推定账户费用授权。现有 runtime 的 `--allow-live/--confirm-cost` 仍需由操作者在实际已获授权时传入。

## 返修和证据变更

```bash
python3 "$FLOW_ROOT/cli.py" stage reopen --task-root "$TASK_ROOT" --step 6.1 --file "$TASK_ROOT/records/reopen.json"
```

输入为 `{"reviewer":"责任人","reason":"具体变化与影响"}`。从最早受影响步骤开始把已做的后续结论标为 `needs_recheck`，保留原始结果和历史记录。后续重验可复用仍匹配的训练证据；文字或格式修订不自动触发重跑。重包后重新独立 QA；只修最终材料时通常回退 6.1，方法/协议变更应回退相应的研究阶段。

`stage status` 检查已通过记录的原件引用哈希；发现漂移给出对应步骤，不静默改为通过。阶段推进与规则升级由一个专家会话串行执行；可并行的训练作业仅通过 W2 的运行账本登记。

题目类型与适配入口在环境验收前通过 `task configure --file ...` 登记，见 [配置模板](templates/task-config.example.json)。`task check` 只查 W1 状态/来源；恢复任务应再运行 `stage status` 检查已登记证据。

QA v0.3.1：6.3 可绑定失败/未完成报告以安排返修；6.4/6.5 须当前独立报告已完成且 PASS。适用项不得使用旧 exception/platform_only 关闭。仅 QA15 固定跳过；QA04/19、H05/06 可按原文及报告一致地 not_applicable。Harbor 动态门禁来源为教程；Skill 的静态 not_run 不解除该要求。
