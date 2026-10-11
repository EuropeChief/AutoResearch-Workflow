<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 3 -->
# 阶段 3：锚点验证与冻结

阶段标识：`anchor_validation`；阶段门提示：`anchor_freeze`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

相关动作前读取已确认决定：`research_contract`。

`anchor_freeze` 需要专家明确确认；程序检查通过不等于批准。
确认绑定已有证据：`anchor_freeze_record`, `formal_protocol`, `score_contract`, `baseline_formal_results`, `reference_formal_results`, `u_estimate`。
确认前可继续准备，不启动对应正式动作；收到真实确认后才追加 `.autoresearch/decision-log.md`。

## 阶段义务

### M02-S3 — 审查并冻结正式 Baseline/Reference

- 规则来源：`M02`（`rules/README.md#M02`）
- 当前行动：用完整证据审查代表性、训练充分性和公平性，冻结正式 B/R 方法与聚合值。
- 所需证据：`baseline_quality_review`, `baseline_formal_results`, `reference_formal_results`, `anchor_freeze_record`
- 检查性质：`review`；严重性：`review`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`M02-S2`, `M03-S2`
- 消费证据：`baseline_candidate`, `baseline_dev_receipts`, `run_protocol`
- 产生证据：`baseline_frozen`, `reference_frozen`, `anchor_freeze_record`
- 影响性变更后复核：`是`

### M03-S3 — 完成正式公平重复

- 规则来源：`M03`（`rules/README.md#M03`）
- 当前行动：按冻结协议完成 B/R 和候选的正式独立 seed 重复、聚合及成对记录。
- 所需证据：`formal_seed_results`, `formal_protocol`, `seed_manifest`, `aggregation`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`M03-S2`, `M02-S2`
- 消费证据：`run_protocol`, `baseline_candidate`
- 产生证据：`formal_seed_results`, `aggregation`
- 影响性变更后复核：`是`

### M04-S3 — 校验锚点与评分公式

- 规则来源：`M04`（`rules/README.md#M04`）
- 当前行动：从全部有效结果复算均值、样本标准差、改善、U 和连续归一化分数，完成可分辨性复核。
- 所需证据：`comparison_summary`, `score_contract`, `u_estimate`, `quality_gate`
- 检查性质：`mixed`；严重性：`review`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`M02-S3`, `M03-S3`
- 消费证据：`formal_seed_results`, `aggregation`
- 产生证据：`score_contract`, `anchor_statistics`
- 影响性变更后复核：`是`

### M07-S3 — 用同版本 Trial 验证 NOP

- 规则来源：`M07`（`rules/README.md#M07`）
- 当前行动：完成当前题包版本的一次正常 NOP，绑定同一评分入口、结果、reward 和日志。
- 所需证据：`nop_trial`, `nop_result`, `nop_reward`, `nop_log`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`M07-S2`, `C05-S2`, `C06-S2`
- 消费证据：`scoring_entry`, `artifact_config`, `task_toml`
- 产生证据：`nop_trial`, `nop_result`, `nop_reward`
- 影响性变更后复核：`是`

### M11-S3 — 绑定 B/R 训练证据

- 规则来源：`M11`（`rules/README.md#M11`）
- 当前行动：确保每个正式 seed 有原始结果、非空日志、模型/产物及干净重载复评分证据。
- 所需证据：`optimization_evidence`, `reload_logs`, `artifact_manifests`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `delivery_qa`
- 读取前置：`M02-S3`, `M03-S3`
- 消费证据：`formal_seed_results`, `aggregation`
- 产生证据：`training_evidence`
- 影响性变更后复核：`是`

### C03-S3 — 冻结正式 seed 与阈值题面

- 规则来源：`C03`（`rules/README.md#C03`）
- 当前行动：把正式 seed、有效提升阈值、工具政策和重复/聚合规则落实到最终 instruction。
- 所需证据：`instruction`, `seed_manifest`, `threshold_statement`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`C03-S1`, `C07-S2`, `M03-S3`
- 消费证据：`instruction_draft`, `formal_seed_results`
- 产生证据：`instruction`, `threshold_statement`
- 影响性变更后复核：`是`

### C05-S3 — 核对正式产物 destination

- 规则来源：`C05`（`rules/README.md#C05`）
- 当前行动：按 Trial 绑定的冻结题包检查唯一主服务 /workspace/solution 的宿主移交路径：显式 destination 按声明，省略或空值才默认；核越界和完整移交，缺失不得回退，Verifier 路径不重映射。
- 所需证据：`artifact_transfer_receipts`, `destination_check`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`C05-S2`, `C06-S2`
- 消费证据：`artifact_config`, `provider_config`
- 产生证据：`destination_check`
- 影响性变更后复核：`是`

### C06-S3 — 验证目标版本实际启动

- 规则来源：`C06`（`rules/README.md#C06`）
- 当前行动：将静态 schema/config 检查与目标 Harbor 版本的实际 Trial/Verifier 启动结果分开记录。
- 所需证据：`native_harbor_trial`, `version_probe`, `startup_log`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`C06-S2`, `M07-S3`
- 消费证据：`provider_config`, `nop_trial`
- 产生证据：`native_harbor_trial`
- 影响性变更后复核：`是`
