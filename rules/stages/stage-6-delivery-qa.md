<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 6 -->
# 阶段 6：材料整理与独立 QA

阶段标识：`delivery_qa`；阶段门提示：`independent_qa`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

本阶段不新增人工批准；相关检查和已有授权满足即可连续推进。

## 阶段义务

### M09-S6 — 整理最终八字段轨迹

- 规则来源：`M09`（`rules/README.md#M09`）
- 当前行动：只对 Agent 生成的真实轮次做允许的格式/摘要修正，输出根 rounds 与八字段完整轨迹。
- 所需证据：`trajectory_codex.json`, `trajectory_seed.json`, `trajectory_review`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M09-S4`, `M10-S5`
- 消费证据：`trajectory_codex`, `trajectory_seed`, `best_method_selection`
- 产生证据：`trajectory_codex.json`, `trajectory_seed.json`, `trajectory_review`
- 影响性变更后复核：`是`

### M10-S6 — 组装唯一最终方法

- 规则来源：`M10`（`rules/README.md#M10`）
- 当前行动：将唯一 best_method 的干净代码、入口和必要配置放入提交面，不放 checkpoint 或历史快照。
- 所需证据：`best_method`, `best_method_manifest`, `clean_tree_check`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M10-S5`, `M11-S5`
- 消费证据：`best_method_snapshot`, `best_artifact_manifest`
- 产生证据：`best_method`, `best_method_manifest`
- 影响性变更后复核：`是`

### M11-S6 — 整理 B/R 与候选证据

- 规则来源：`M11`（`rules/README.md#M11`）
- 当前行动：将 B/R 全 seed 结果、原始日志、模型/重载记录和 comparison_summary 按包内相对路径绑定。
- 所需证据：`optimization_evidence`, `training_evidence_index`, `comparison_summary`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M11-S3`, `M11-S5`, `M10-S5`
- 消费证据：`training_evidence`, `best_reload_log`
- 产生证据：`training_evidence_index`, `comparison_summary`
- 影响性变更后复核：`是`

### M12-S6 — 按最小充分结构组包

- 规则来源：`M12`（`rules/README.md#M12`）
- 当前行动：组装 workspace、expert_evidence、optimization_evidence 三目录及题面八部分，移除无证明作用的流程文件。
- 所需证据：`package_root`, `package_manifest`, `submission_structure_check`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M09-S6`, `M10-S6`, `M11-S6`, `C07-S5`
- 消费证据：`trajectory_review`, `best_method`, `training_evidence_index`
- 产生证据：`package_root`, `package_manifest`
- 影响性变更后复核：`是`

### M13-S6 — 独立 QA 后直接交付

- 规则来源：`M13`（`rules/README.md#M13`）
- 当前行动：由用户在独立会话以最终包为唯一边界完成 QA；适用项通过后直接打三包 ZIP。
- 所需证据：`independent_qa_report`, `package_archives`, `delivery_index`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M12-S6`
- 消费证据：`package_root`, `package_manifest`
- 产生证据：`package_archives`, `delivery_index`
- 影响性变更后复核：`是`

- 以下动作前不要求运行后结果：`independent_qa`；阶段退出时再核。

### C02-S6 — 按条件记录 Git 线索处理

- 规则来源：`C02`（`rules/README.md#C02`）
- 当前行动：若 Agent 可见内容存在 .git，核 remotes/tags/reflog 和答案线索；无 .git 则不造清理任务。
- 所需证据：`git_visibility_check`, `git_clue_review`
- 检查性质：`review`；严重性：`review`
- 阶段门前阻断：`independent_qa`
- 读取前置：`M12-S6`
- 消费证据：`package_root`
- 产生证据：`git_clue_review`
- 影响性变更后复核：`是`

### C03-S6 — 终稿题面与轨迹一致

- 规则来源：`C03`（`rules/README.md#C03`）
- 当前行动：检查最终 instruction、两轨 prompt、seed/阈值和提交说明之间没有旧题面或相互矛盾。
- 所需证据：`instruction_final`, `prompt_consistency_check`, `legacy_text_scan`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`C03-S3`, `C03-S4`, `M09-S6`
- 消费证据：`instruction`, `prompt_hashes`, `trajectory_review`
- 产生证据：`prompt_consistency_check`, `legacy_text_scan`
- 影响性变更后复核：`是`

### C07-S6 — 完成全包字段与目录检查

- 规则来源：`C07`（`rules/README.md#C07`）
- 当前行动：按当前教程与 QA 原件检查根结构、JSON/JSONL 字段、中文专家材料和相对路径引用。
- 所需证据：`format_check`, `schema_check`, `relative_path_check`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`independent_qa`
- 读取前置：`C07-S5`, `M12-S6`
- 消费证据：`field_check`, `package_root`
- 产生证据：`format_check`, `schema_check`
- 影响性变更后复核：`是`
