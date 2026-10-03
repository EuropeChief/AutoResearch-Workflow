---
name: autoresearch-optimization-surface
description: 辅助从论文与代码中比较 AutoResearch 优化面，明确方法空间、Baseline/Reference 候选和最小验证实验。用于阶段 1.2 或优化方向调整。
---

# 优化面分析辅助

本 Skill 提供研究设计建议。执行顺序、规则、证据和验收沿用当前 AutoResearch 流程及任务合同；不新增门禁、检查或独立报告。

结合论文、已有实现与可用资源，按 [分析要点](references/surface-analysis.md) 比较候选方向。沿真实代码入口说明允许改变的方法、固定因素、Baseline/Reference 候选、指标与成本；把尚未验证的假设与已有实验结论区分开。

优先寻找算法、结构、计算图或资源生命周期上的方法空间，说明它与固定算法的纯参数搜索有什么区别。提出能回答关键可行性问题的最小实验，按当前阶段已有授权和实验协议执行；已有证据足够时直接复用。

将推荐方向、必要备选及退出条件写入现有 `research/design.md` 或任务已使用的设计文档。优化面发生实质变化时可再次调用，不要求每阶段重复分析。

改编自 `autoresearch-skills/skills/autoresearch-optimization-surface`，已将独立门禁表述适配为辅助建议。原作者：AutoResearch Skills contributors（2026）；[MIT 许可](LICENSE.md)。
