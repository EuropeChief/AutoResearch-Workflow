---
name: autoresearch-research
description: 研究 AutoResearch 论文与代码，探索优化面和 Baseline/Reference 方向，判断科学与资源可行性。适用于新题、方法范围调整和内容门返修，不在探索期提前冻结锚点。
---

# 研究与设计

需要用户指定的题目、论文/代码或可靠来源，以及已知资源约束。先读已有研究和实际结果；缺少决定性材料才询问，不从其他题目推断。

1. 沿代码入口说明任务输入输出、指标、允许变化和固定因素。判断接口是否真正支持方法设计，而非固定方法中的数字搜索；依据[方法空间](../../rules/README.md#m01)。
2. 区分 Starter、正式 Baseline、Reference 候选，解释来源、代表性和差异。先提出方向与待证假设，不拿预想分数冻结 B/R。合理 naive 不等于故障或无依据少训练；依据[Baseline](../../rules/README.md#m02)。
3. 对最关键不确定性设计最小探索实验：什么观察支持或否定方向、费用是否可承受、何时转向。用[实验能力](../autoresearch-experiment-validation/SKILL.md)验证；已有同条件证据可复用，不默认全网格或额外 Expert Best 搜索。
4. 形成推荐优化面、B/R 方向、固定协议草案及未决问题，写入已有研究记录。验证后再与实验能力共同确定评分锚点；U 依据及剩余空间按[评分要求](../../rules/README.md#m04)，不从目标分数倒推。

需要设计启发时使用 [optimization-surface](../autoresearch-optimization-surface/SKILL.md)；写题面时交给[任务实现](../autoresearch-task-implementation/SKILL.md)，可参考 [task-authoring](../autoresearch-task-authoring/SKILL.md)。辅助 Skill 不增加门禁或独立报告。

产物是可执行的研究方向、证据和下一实验，不是“阶段通过”声明。新题在合理范围建立 Git 检查点，已有仓库先核状态，避免把大数据、模型、凭据和日志纳入；这是工作习惯，不是科学通过证据。
