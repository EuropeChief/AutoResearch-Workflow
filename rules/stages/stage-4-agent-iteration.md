<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 4 -->
# 阶段 4：双轨 Agent 迭代

阶段标识：`agent_iteration`；阶段门提示：`dual_track_launch`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

相关动作前读取已确认决定：`research_contract`, `anchor_freeze`。

`dual_track_launch` 需要专家明确确认；程序检查通过不等于批准。
确认绑定已有证据：`track_configs`, `track_runtime_configs`, `prompt_hashes`, `duration_assessment`, `track_image_ids`, `exposure_manifest`。
确认前可继续准备，不启动对应正式动作；收到真实确认后才追加 `.autoresearch/decision-log.md`。

## 阶段义务

### M05-S4 — 双轨启动前复核可见性

- 规则来源：`M05`（`rules/README.md#M05`）
- 当前行动：在正式迭代前确认每轨只能读取题面、Starter、公开反馈和本轨输出。
- 所需证据：`dual_track_exposure_probe`, `exposure_manifest`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`M05-S2`, `C05-S3`
- 消费证据：`exposure_manifest`, `destination_check`
- 产生证据：`dual_track_exposure_probe`
- 影响性变更后复核：`是`

### M07-S4 — 双轨评分入口预检

- 规则来源：`M07`（`rules/README.md#M07`）
- 当前行动：确认两轨均可通过同一可信入口得到公开分数，NOP/候选路径无异常。
- 所需证据：`track_scoring_probe`, `nop_result`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`M07-S3`, `C04-S2`
- 消费证据：`nop_result`, `entry_probe`
- 产生证据：`track_scoring_probe`
- 影响性变更后复核：`是`

### M08-S4 — 冻结双轨运行与净时长口径

- 规则来源：`M08`（`rules/README.md#M08`）
- 当前行动：为两轨分别固定模型/Prompt/资源、10h 或有依据的 7h 资格、净时长计时和中断续接规则。 在既有双轨启动前检查中保留格式脚本原结果和时点解释，保存真实起始题包快照及四项指纹。
- 所需证据：`track_configs`, `duration_assessment`, `timing_ledger`, `session_identity`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`M02-S3`, `M03-S3`, `M07-S3`, `C03-S3`
- 消费证据：`baseline_frozen`, `run_protocol`, `nop_trial`, `instruction`
- 产生证据：`track_configs`, `duration_assessment`, `timing_ledger`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`track_configs`, `duration_assessment`, `timing_plan`, `session_policy`, `format_precheck`, `task_binding`

### M09-S4 — 保存 Agent 原生轨迹

- 规则来源：`M09`（`rules/README.md#M09`）
- 当前行动：让每轨迭代 Agent 生成真实轮次 JSONL、操作日志、输出和会话续接依据。
- 所需证据：`trajectory_codex`, `trajectory_seed`, `operation_logs`, `session_resume`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`, `best_method_retest`
- 读取前置：`M08-S4`, `C03-S4`
- 消费证据：`track_configs`, `duration_assessment`
- 产生证据：`trajectory_codex`, `trajectory_seed`, `operation_logs`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`trajectory_contract`, `logging_config`, `resume_policy`

### C01-S4 — 运行期结果仍由可信入口写入

- 规则来源：`C01`（`rules/README.md#C01`）
- 当前行动：检查双轨候选不能预写/伪造 reward，运行日志保留实际评分调用。
- 所需证据：`track_reward_receipts`, `reward_cleanup_test`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`C01-S2`, `M07-S4`
- 消费证据：`reward_cleanup_test`, `track_scoring_probe`
- 产生证据：`track_reward_receipts`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`track_reward_probe`, `reward_cleanup_test`

### C03-S4 — 按冻结题面运行双轨

- 规则来源：`C03`（`rules/README.md#C03`）
- 当前行动：核对两轨使用同一题面、公开协议和工具边界，修改只能发生在合法工作面。
- 所需证据：`prompt_hashes`, `track_policy_logs`, `write_scope_probe`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`C03-S3`, `M08-S4`
- 消费证据：`instruction`, `track_configs`
- 产生证据：`prompt_hashes`, `track_policy_logs`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`prompt_hashes`, `write_scope_probe`

### C04-S4 — 记录每次入口与失败分类

- 规则来源：`C04`（`rules/README.md#C04`）
- 当前行动：保存双轨评分调用和有限 reward，区分方法失败、Hard Gate、超时、资源及基础设施异常。
- 所需证据：`score_calls`, `failure_classification`, `reward_receipts`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`, `best_method_retest`
- 读取前置：`C04-S2`, `C01-S4`
- 消费证据：`entry_probe`, `track_reward_receipts`
- 产生证据：`score_calls`, `failure_classification`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`entry_probe`, `failure_policy`

### C05-S4 — 保留双轨路径与移交证据

- 规则来源：`C05`（`rules/README.md#C05`）
- 当前行动：启动前复核每轨冻结声明与真实宿主 destination，Verifier 内保持 source；之后保留 Agent 镜像、Verifier 入口与候选/模型/配置的实际移交证据。
- 所需证据：`track_image_ids`, `artifact_transfer_receipts`, `verifier_receipts`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`C05-S3`, `M08-S4`
- 消费证据：`destination_check`, `track_configs`
- 产生证据：`track_image_ids`, `verifier_receipts`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`track_image_ids`, `artifact_transfer_probe`, `verifier_probe`

### C06-S4 — 记录双轨实际配置

- 规则来源：`C06`（`rules/README.md#C06`）
- 当前行动：保留实际模型、provider、GPU/资源、Harbor 和启动配置，证明运行配置确实生效。
- 所需证据：`track_runtime_configs`, `model_metadata`, `launch_logs`
- 检查性质：`mechanical`；严重性：`hard`
- 阶段门前阻断：`dual_track_launch`
- 读取前置：`C06-S3`, `M08-S4`
- 消费证据：`native_harbor_trial`, `track_configs`
- 产生证据：`track_runtime_configs`, `model_metadata`
- 影响性变更后复核：`是`

- `dual_track_launch` 前先核准备证据：`track_runtime_configs`, `model_metadata`, `startup_probe`
