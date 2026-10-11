# 题目阶段门决定记录

本文件只记录研究合同、锚点冻结和双轨启动等关键决定，采用追加方式。
普通实验动作不写入此处；文件不作为最终提交包材料。
仅在收到真实专家/用户答复后记录；不复制示例为实际批准。
从 preflight 的 confirmations[].proposal 取 rule_version、evidence、bindings，
专家不手工填哈希。其余两种确认使用 anchor_freeze、dual_track_launch 标题及各自 proposal。

## 2026-01-01T00:00:00Z — research_contract

- status: approved
- scope: 本次题目的优化面、指标和 Public/Dev 草案
- rule_version: 替换为 proposal 的当前 rule_version
- evidence: research_contract.json; anchor_candidates.md; protocol_draft.json
- bindings: {"research_contract":{"path":"research_contract.json","sha256":"替换为实际哈希"},"anchor_candidates":{"path":"anchor_candidates.md","sha256":"替换为实际哈希"},"protocol_draft":{"path":"protocol_draft.json","sha256":"替换为实际哈希"}}
- approver: 专家姓名或项目方
- limits: 仍需在阶段 3 验证并冻结 Baseline/Reference

evidence 是 bindings 中文件的分号分隔列表；多项引用同一文件时只列一次。
status 可为 approved、pending、rejected；专家豁免本节点时用 waived，并另写 reason，
但不自动豁免具体检查项或资源授权。最新决定覆盖本节点旧记录，撤回用追加 rejected，
记录无效也不恢复旧批准；不要修改前条或为普通操作新增节点。

## 2026-01-02T00:00:00Z — exception

- status: waived
- scope: M03-S1
- before: research_contract
- rule_version: 替换为 preflight 输出的当前 rule_version
- reason: 真实特殊情况与风险，不以省事或 Agent 自行决定代替确认
- evidence: approvals/specific-confirmation.md
- approver: 实际确认的用户或专家
- limits: 仅当前题目/版本/动作适用；不豁免费用和权限授权

例外用明确义务 ID（多项逗号分隔），证据为题目根内非空确认依据文件。
没有专家确认时仍为 PENDING/BLOCKED；无条件要求不得改成 not_applicable。
例外修改继续追加，不改写前条；最新 rejected 可撤回同范围例外。
