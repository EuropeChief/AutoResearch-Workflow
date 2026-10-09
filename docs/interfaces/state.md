# 状态与证据：统一登记和接续（历史兼容接口）

> 本页只保留给依赖旧状态账本的历史任务。新题不初始化 `.autoresearch-flow`，请从[六阶段导航](../stages.md)和当前能力入口开始。

此模块登记阶段状态并复用实验、运行和交付检查，不运行训练、调用模型或代替独立 QA。题目根下使用 `.autoresearch-flow/state.json` schema 2；不可覆盖记录在 `.autoresearch-flow/stage_records/`。

政策随新任务冻结，见 [Git](task-git.md)、[稳定性](environment.md)、[时长](duration.md)。只支持新任务和同版本恢复；旧状态只读拒绝，不自动补值或迁移。

## 常用命令

```bash
python3 "$FLOW_ROOT/cli.py" --format json stage status --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json stage check --task-root "$TASK_ROOT" --step 2.5 --file "$TASK_ROOT/records/step-2.5.json"
python3 "$FLOW_ROOT/cli.py" --format json stage template --task-root "$TASK_ROOT" --step 2.5
python3 "$FLOW_ROOT/cli.py" --format json stage ref --task-root "$TASK_ROOT" --path evidence/note.md --path evidence/log.txt
python3 "$FLOW_ROOT/cli.py" stage record --task-root "$TASK_ROOT" --file "$TASK_ROOT/records/step-2.5.json"
python3 "$FLOW_ROOT/cli.py" stage finish --task-root "$TASK_ROOT" --stage 2 --file "$TASK_ROOT/records/finish-2.json"
```

`stage template` 返回 JSON 中的 `spec` 是待填写输入；保存 **spec 内容本身**，不要连 `status` 等外层一起传回。`stage ref` 为已存在的任务内文件计算实际 SHA-256，不复制、不修改证据。模板中的示例和占位符均不是验收证据。

`stage status` 只展示当前子步骤的规则索引、准备证据和审查提示；全文用 `rules show --step` 查看。`stage check` 只读重算该步骤已有门禁，`--file` 可省略；不启动实验、不推进状态、不需要人工点击确认。机器结果与实质审查记录分开返回，`scientific_conclusion_certified=false` 表示程序不认证科学判断。

`check/record` 可复用前面已通过记录中仍有效的协议、合同和文件引用；缺项须明确提供，不猜文件位置，不推断批准。`resolved_checks` 显示实际输入；`record/finish` 自动保存检查结果与来源锁，无需手抄统计输出。变更输入须给新引用，证据漂移须查明后按影响重开。

`record` 至少含 `step/status/reviewer/summary/evidence/checks`；可加 `inputs/outputs` 引用数组。所有引用为 `{"path":"任务内相对文件","sha256":"真实64位SHA-256"}`。同一说明或原始日志可被多个子步骤引用，无需为每步复制证据文件。

记录状态为 `in_progress`、`failed`、`awaiting_evidence` 或 `passed`。前三种保留当前步骤，不提前推进；等待证据须填当前 `due_stage`。只有完成全部子步骤后才可 finish。跨阶段可暂缓的是 B03/B07 的**跨方法部分**，在阶段 2 的 `baseline_review` 中按实验工具记录；当前可判部分仍须通过，阶段 3 必须关闭。`record` 保存失败记录时以非零退出码提示；已登记事实仍保留。

## 程序检查与专家判断

阶段 1.2、1.3、2.2 的模板含最小 `reviews`：`rule_id/status/rationale/evidence/unresolved`；待补证可加 `due_stage`，但整个未完成步骤不能跨阶段判通过。1.2 的 AR-002 结合题面、允许修改范围和已有代码判断方法设计空间；2.2 再按已实现接口与可修改代码复核。仅宣称“允许改算法”不够。1.3 的 AR-003 只说明候选理由，不能提前冻结未经验证的锚点。

Baseline 复用 B01–B08 入口，不另写一套报告。阶段 2 冻结前，执行 Agent 沿代码、训练充分性、代表性和公平证据审查；“能跑通”或“比 Reference 差”均不足以判合理。B03/B07 仅跨方法部分可延期，当前可判部分仍须通过，到阶段 3 未补审则不能关闭。可引用同一研究/实验记录，无须每项另写文件。程序只核记录与引用是否齐备，不证明理由科学正确；用户只在既有关键节点审阅和决定冻结，不新增逐项审批。

| 步骤 | 自动重核的事实 |
|---|---|
| 1.1（当前政策的新任务） | Git 范围已确认且存在真实、可追溯的初始检查点 |
| 2.1 | 双镜像结构及真实 Harbor 最小移交/独立评分记录；结构检查不替代实跑 |
| 2.3 |实验工具正式协议已锁定 |
| 2.4 / 3.2 / 5.2 | 对应角色正式 seed 完整性及实验工具统计报告 |
| 2.5 / 3.3 / 3.5 | B01–B08 完整专家审查、证据和方法/协议绑定；阶段 3 不可遗留 deferred |
| 3.4 / 3.5 |实验工具评分合同、U 依据引用、数值锚点；3.5 另核绑定冻结合同的 Harbor 出分 |
| 4.1 | 当前任务 Harbor 实跑、两组真实预检、预算批准引用与冻结时长快照；7h资格须在prepare之前确认 |
| 4.4 | 各轨独立达到冻结净时长（默认10h/合格7h）、已停止、不同会话、Agent自写轨迹；7h另核至少3轮方法闭环、演进和可继续方向 |
| 5.1 / 5.3 / 5.4 | 唯一方法快照、正式复验绑定、干净快照重跑 |
| 6.1 / 6.2 | 当前最终包的格式检查 |
| 6.3 | 当前包绑定了独立 QA 原报告，报告未被改动 |
| 6.4 / 6.5 | 逐项处置覆盖报告检查项、绑定包/报告，明确不存在未解决本地项；报告未通过项不能手改成 pass |

6.5 另核最终包内 Harbor 实跑、最佳代码与实际候选清单/评分合同绑定；只读检查报告 `qa_verified → archives_verified → form_ready` 的当前位置。正式登记/完成阶段要求 `form_ready`，见 [交付顺序](delivery.md#顺序与命令)。不要求 `checks.stability`；省略时如实记为 `not_run`，提供时仍核真实 12h、镜像、无异常及包内证据。内部记录格式与范围见 [环境接口](environment.md)，不是新增平台必填文件名。

其余步骤登记专家的实际判断与证据，不自动证明论文方法、Baseline 代表性、合法迭代或模型能力。`finish` 会重新检查当前阶段所有实际程序门禁，并核阶段 2/3 使用同一个正式协议，阶段 6 全部步骤对应同一包版本。

3σ–5σ 按教程允许追加正式重复后标记平台复核，不提高为统一 5σ 硬门。该情形在 3.3/3.4/3.5 的 `checks` 中增加 `statistical_review` 文件引用：文件绑定当前 `protocol_sha256`、`experiment_sha256`，含 `platform_review_required:true`、`reviewer/rationale/evidence`。程序要求实验工具有追加 seed 且两侧完整；不能用此说明覆盖负增益、<3σ、失败的 Baseline 项或非法评分。

## 冻结与确认

`finish` 输入见 [阶段结束模板](../../templates/stage-finish.example.json)。不要求每阶段重复抄录教程章节；来源锁和重核结果自动绑定。确有原文歧义或提炼遗漏时回查锁定原文，可用可选 `source_review={findings,resolution,evidence}` 记录实际问题和依据，未解决问题不能用空泛“已核对”代替处理。来源字节变化仍按漂移处理，不在 finish 中自动接受新规则。

阶段 1、2、3、6 的结束记录须引用用户确认；4.1 须引用双轨预算批准。确认文件形状见 [确认模板](../../templates/confirmation.example.json)，真实确认后将 `approved` 填为 `true`，`scope` 分别为 `stage-1/2/3/6` 或 `stage-4-start`。引用既有用户明确指示即可，不需要每条命令重复询问。不得把专家自己的建议写成用户已批准。

审批引用只记录来源与范围；工具不会推定账户费用授权。现有 runtime 的 `--allow-live/--confirm-cost` 仍需由操作者在实际已获授权时传入。

## 返修和证据变更

```bash
python3 "$FLOW_ROOT/cli.py" stage reopen --task-root "$TASK_ROOT" --step 6.1 --file "$TASK_ROOT/records/reopen.json"
```

输入为 `{"reviewer":"责任人","reason":"具体变化与影响"}`。从最早受影响步骤开始把已做的后续结论标为 `needs_recheck`，保留原始结果和历史记录。后续重验可复用仍匹配的训练证据；文字或格式修订不自动触发重跑。重包后重新独立 QA；只修最终材料时通常回退 6.1，方法/协议变更应回退相应的研究阶段。

`stage status` 检查已通过记录的原件引用哈希；发现漂移给出对应步骤，不静默改为通过。阶段状态写入由一个专家会话串行执行；可并行的训练作业仅通过实验工具的运行账本登记。

题目类型与适配入口在环境验收前通过 `task configure --file ...` 登记，见 [配置模板](../../templates/task-config.example.json)。`task check` 只查流程状态/来源；恢复任务应再运行 `stage status` 检查已登记证据。

QA v0.3.2：6.3 可绑定缺 NOP 的 FAIL/not_run 报告以安排返修；6.4/6.5 须当前独立报告已完成且 PASS。适用项不得使用旧 exception/platform_only 关闭。仅 QA15 固定跳过；QA04/19、H05 可按原文及报告一致地 not_applicable，H06 必查。Harbor 动态门禁来源为教程；缺 NOP 的 not_run 与 H06/QA17 失败，不能用于收口。
