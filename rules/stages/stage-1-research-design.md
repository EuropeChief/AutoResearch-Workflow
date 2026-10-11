<!-- generated-from: rules/stage_matrix.json; do not edit manually -->
<!-- stage: 1 -->
# 阶段 1：研究设计

阶段标识：`research_design`；阶段门提示：`research_contract`。
本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。
规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。

`research_contract` 需要专家明确确认；程序检查通过不等于批准。
确认绑定已有证据：`research_contract`, `anchor_candidates`, `protocol_draft`。
确认前可继续准备，不启动对应正式动作；收到真实确认后才追加 `.autoresearch/decision-log.md`。

## 阶段义务

### M01-S1 — 界定真实方法空间

- 规则来源：`M01`（`rules/README.md#M01`）
- 当前行动：在研究合同中说明可编程改进面、合法接口和至少一个题面未直接提示的方向。
- 所需证据：`research_notes`, `research_contract`
- 检查性质：`review`；严重性：`review`
- 阶段门前阻断：`research_contract`
- 读取前置：无
- 消费证据：无
- 产生证据：`research_contract`
- 影响性变更后复核：`是`

### M02-S1 — 提出 Baseline/Reference 候选方向

- 规则来源：`M02`（`rules/README.md#M02`）
- 当前行动：记录候选 Baseline、Reference、预期锚点和选择理由；此阶段只定方向，不提前冻结分数。
- 所需证据：`research_notes`, `anchor_candidates`
- 检查性质：`review`；严重性：`review`
- 阶段门前阻断：`research_contract`
- 读取前置：`M01-S1`
- 消费证据：`research_contract`
- 产生证据：`anchor_candidates`
- 影响性变更后复核：`是`

### M03-S1 — 拟定公平实验协议

- 规则来源：`M03`（`rules/README.md#M03`）
- 当前行动：先写明数据、切分、指标、预算、正式 seed、重复/聚合和选择规则。
- 所需证据：`protocol_draft`, `data_split_fingerprint`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`research_contract`, `task_ready`
- 读取前置：无
- 消费证据：无
- 产生证据：`protocol_draft`
- 影响性变更后复核：`是`

### C03-S1 — 起草题面约束与工具政策

- 规则来源：`C03`（`rules/README.md#C03`）
- 当前行动：在题面草稿中写明随机 seed、有效提升阈值、网络/检索/工具、可写范围和并发政策。
- 所需证据：`instruction_draft`, `protocol_draft`
- 检查性质：`mixed`；严重性：`hard`
- 阶段门前阻断：`research_contract`, `task_ready`
- 读取前置：`M03-S1`
- 消费证据：`protocol_draft`
- 产生证据：`instruction_draft`
- 影响性变更后复核：`是`
