<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 2 -->
# 阶段 2：任务实现与候选基线

阶段标识：`task_implementation`；阶段门提示：`task_ready`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

相关动作前读取已确认决定：`research_contract`。

本阶段不新增人工批准；相关检查和已有授权满足即可连续推进。

## 阶段义务

### M02-S2 — 实现并试跑朴素 Baseline

- 规则来源：`M02`（`rules/README.md#M02`）
- 当前行动：实现可运行的 Starter/朴素 Baseline，按草案协议取得可追溯 Public/Dev 结果。
- 所需证据：`baseline_source`, `baseline_smoke`, `baseline_dev_receipts`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`
- 读取前置：`M01-S1`, `M02-S1`, `M03-S1`
- 消费证据：`anchor_candidates`, `protocol_draft`
- 产生证据：`baseline_candidate`, `baseline_dev_receipts`
- 影响性变更后复核：`是`

### M03-S2 — 把公平协议落到运行配置

- 规则来源：`M03`（`rules/README.md#M03`）
- 当前行动：固定训练/评估数据、切分指纹、预算、seed 输入和聚合方式，供 B/R 与候选共用。
- 所需证据：`task_config`, `split_hash`, `run_protocol`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`anchor_freeze`, `dual_track_launch`
- 读取前置：`M03-S1`, `C03-S1`
- 消费证据：`protocol_draft`, `instruction_draft`
- 产生证据：`run_protocol`
- 影响性变更后复核：`是`

### M05-S2 — 实现 Agent 可见性边界

- 规则来源：`M05`（`rules/README.md#M05`）
- 当前行动：建立题面、Starter、公开数据/Dev 和合法输出的可见面，并记录私有内容与另一轨不可见。
- 所需证据：`exposure_manifest`, `image_layout`, `visibility_probe`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `dual_track_launch`
- 读取前置：`C03-S1`
- 消费证据：`instruction_draft`
- 产生证据：`exposure_manifest`, `visibility_probe`
- 影响性变更后复核：`是`

### M06-S2 — 实现题面硬约束

- 规则来源：`M06`（`rules/README.md#M06`）
- 当前行动：让环境、评分逻辑或可信恢复实际执行题面限制，并保留必要的只读/校验保护。
- 所需证据：`hard_gate_tests`, `trusted_restore_probe`, `constraint_implementation`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `dual_track_launch`
- 读取前置：`C03-S1`
- 消费证据：`instruction_draft`
- 产生证据：`constraint_implementation`, `hard_gate_tests`
- 影响性变更后复核：`是`

### M07-S2 — 接通评分与 NOP 链路

- 规则来源：`M07`（`rules/README.md#M07`）
- 当前行动：实现公开反馈、候选移交、独立 Verifier/reward 和当前题包版本的 NOP 入口。
- 所需证据：`scoring_entry`, `verifier_source`, `nop_plan`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `anchor_freeze`, `dual_track_launch`
- 读取前置：`M03-S2`, `M05-S2`, `M06-S2`
- 消费证据：`run_protocol`, `exposure_manifest`, `constraint_implementation`
- 产生证据：`scoring_entry`, `nop_plan`
- 影响性变更后复核：`是`

### C01-S2 — 清理并可信写入结果

- 规则来源：`C01`（`rules/README.md#C01`）
- 当前行动：在可信评分入口清理候选预写结果，实际计算并写入 reward。
- 所需证据：`reward_cleanup_test`, `verifier_source`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `dual_track_launch`
- 读取前置：`M07-S2`
- 消费证据：`scoring_entry`
- 产生证据：`reward_cleanup_test`
- 影响性变更后复核：`是`

### C04-S2 — 固定入口、输出和 Hard Gate

- 规则来源：`C04`（`rules/README.md#C04`）
- 当前行动：验证单命令评分调用、必填参数、reward 输出、超时/资源失败和非作弊 Hard Gate 的分类。
- 所需证据：`entry_probe`, `reward_format_test`, `hard_gate_receipts`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `dual_track_launch`
- 读取前置：`M07-S2`, `C01-S2`
- 消费证据：`scoring_entry`, `reward_cleanup_test`
- 产生证据：`entry_probe`, `reward_format_test`
- 影响性变更后复核：`是`

### C05-S2 — 落实双镜像和产物路径

- 规则来源：`C05`（`rules/README.md#C05`）
- 当前行动：配置 Agent/Verifier 双镜像、COPY/WORKDIR/入口和候选移交；区分容器 source、宿主 artifacts/destination 与 Verifier 内原源路径。静态审阅镜像源构建到实际运行的接入、随包/外置资产的取得与身份校验、可配置宿主路径，结论并入已有实现材料。
- 所需证据：`docker_path_contract`, `artifact_config`, `artifact_transfer_probe`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `anchor_freeze`, `dual_track_launch`
- 读取前置：`M05-S2`, `M07-S2`
- 消费证据：`exposure_manifest`, `scoring_entry`
- 产生证据：`docker_path_contract`, `artifact_config`
- 影响性变更后复核：`是`

### C06-S2 — 固定目标版本配置

- 规则来源：`C06`（`rules/README.md#C06`）
- 当前行动：让 task/provider/agent、Verifier 和启动条件使用目标 Harbor schema 与实际适配入口。沿部署入口至评分 worker 静态审阅可信设备分配是否一致、组件版本是否可取得并按说明调用；不只检查入口可配置。
- 所需证据：`task_toml`, `provider_config`, `version_probe`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`task_ready`, `anchor_freeze`, `dual_track_launch`
- 读取前置：`C05-S2`
- 消费证据：`docker_path_contract`
- 产生证据：`task_toml`, `provider_config`
- 影响性变更后复核：`是`

### C07-S2 — 建立当前字段格式骨架

- 规则来源：`C07`（`rules/README.md#C07`）
- 当前行动：按当前教程建立 instruction、task、训练结果和专家材料的字段骨架，避免旧版字段混入。
- 所需证据：`format_templates`, `task_contract`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`task_ready`
- 读取前置：`C03-S1`
- 消费证据：`instruction_draft`
- 产生证据：`format_templates`, `task_contract`
- 影响性变更后复核：`是`
