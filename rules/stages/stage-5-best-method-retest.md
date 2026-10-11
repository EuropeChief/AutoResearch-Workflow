<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 5 -->
# 阶段 5：最佳方法复验

阶段标识：`best_method_retest`；阶段门提示：`best_method_retest`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

本阶段不新增人工批准；相关检查和已有授权满足即可连续推进。

## 阶段义务

### M03-S5 — 按同协议复验候选

- 规则来源：`M03`（`rules/README.md#M03`）
- 当前行动：对最终唯一候选按冻结数据、预算、seed 与聚合规则完成独立干净复验。
- 所需证据：`best_retest_runs`, `best_retest_summary`, `retest_protocol`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`best_method_retest`, `independent_qa`
- 读取前置：`M03-S3`, `M08-S4`, `M09-S4`
- 消费证据：`formal_protocol`, `trajectory_codex`, `trajectory_seed`
- 产生证据：`best_retest_runs`, `best_retest_summary`
- 影响性变更后复核：`是`

- `best_method_retest` 前先核准备证据：`retest_protocol`, `best_method_selection`, `best_method_snapshot`

### M04-S5 — 复算最终改善与评分

- 规则来源：`M04`（`rules/README.md#M04`）
- 当前行动：从全部有效复验结果复算均值、样本标准差、3σ 判据和最终归一化分数。
- 所需证据：`best_retest_summary`, `final_score_recalculation`, `quality_gate`
- 检查性质：`mixed`；严重性：`review`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M04-S3`, `M03-S5`
- 消费证据：`best_retest_runs`, `score_contract`
- 产生证据：`final_score_recalculation`
- 影响性变更后复核：`是`

- 以下动作前不要求运行后结果：`best_method_retest`；阶段退出时再核。

### M10-S5 — 确定唯一 best_method

- 规则来源：`M10`（`rules/README.md#M10`）
- 当前行动：比较两轨有效结果，选择唯一方法并在干净快照中恢复、运行和记录复验。
- 所需证据：`best_method_selection`, `best_method_snapshot`, `best_method_retest`
- 检查性质：`review`；严重性：`review`
- 阶段门前阻断：`best_method_retest`, `independent_qa`
- 读取前置：`M09-S4`, `M03-S5`, `M04-S5`
- 消费证据：`trajectory_codex`, `trajectory_seed`, `best_retest_summary`
- 产生证据：`best_method_selection`, `best_method_snapshot`
- 影响性变更后复核：`是`

- `best_method_retest` 前先核准备证据：`best_method_selection`, `best_method_snapshot`

### M11-S5 — 核对最终模型重载

- 规则来源：`M11`（`rules/README.md#M11`）
- 当前行动：对最终方法所需模型/产物做干净进程重载和复评分，保留真实日志与哈希绑定。
- 所需证据：`best_reload_log`, `best_artifact_manifest`, `best_reload_score`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M11-S3`, `M10-S5`
- 消费证据：`training_evidence`, `best_method_snapshot`
- 产生证据：`best_reload_log`, `best_artifact_manifest`
- 影响性变更后复核：`是`

- 以下动作前不要求运行后结果：`best_method_retest`；阶段退出时再核。

### C07-S5 — 验证复验结果字段

- 规则来源：`C07`（`rules/README.md#C07`）
- 当前行动：检查候选复验 result、comparison 和专家记录包含当前协议、seed、指标、路径与状态字段。
- 所需证据：`retest_result_json`, `comparison_summary`, `field_check`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`C07-S2`, `M03-S5`
- 消费证据：`format_templates`, `best_retest_runs`
- 产生证据：`field_check`
- 影响性变更后复核：`是`

- 以下动作前不要求运行后结果：`best_method_retest`；阶段退出时再核。
