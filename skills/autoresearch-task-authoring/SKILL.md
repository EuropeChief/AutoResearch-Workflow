---
name: autoresearch-task-authoring
description: 辅助将 AutoResearch 研究方向整理为清晰题面、方法接口、Starter 与评分合同。用于任务实现或合同发生实质调整时，不增加独立门禁。
---

# 题面与接口设计辅助

本 Skill 提供设计建议。规则和证据沿用[当前要求](../../rules/README.md)及任务合同；不运行来源 Skill 的五套门禁，不新增检查、脚本或独立报告。

结合已选研究方向、论文与实际代码，按 [设计要点](references/authoring-notes.md) 整理题面和接口。把允许修改面、固定因素、输入输出、预算、目标与失败条件表达清楚，使题面描述与可执行实现一致。

分别解释 Starter、正式 Baseline 与 Reference 候选的职责，说明评分器怎样从候选的真实运行独立计算指标。检查题面是否意外披露 Reference 方法、Hidden 材料或专家私有信息。

直接完善现有设计文档、`instruction.md` 和接口说明。尚未验证的 Baseline、Reference、评分锚点仍作为候选或假设，验证和冻结使用[实验能力](../autoresearch-experiment-validation/SKILL.md)。任务合同发生实质调整时可再次调用。

改编自 `autoresearch-skills/skills/autoresearch-task-authoring`，保留题目设计建议并移除独立流程操作。原作者：AutoResearch Skills contributors（2026）；[MIT 许可](LICENSE.md)。
