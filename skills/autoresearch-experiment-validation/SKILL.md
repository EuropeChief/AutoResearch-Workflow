---
name: autoresearch-experiment-validation
description: 执行或分析 AutoResearch 可行性实验、Baseline/Reference 公平标定和最终最佳方法复验。依据真实协议与逐次结果判断，不要求流程账本，不默认重跑已有实验。
---

# 实验验证

先明确这次是探索、正式标定、统计已有结果，还是唯一最终方法复验。需要方法入口、实际协议、输入证据/输出位置及运行所需资源授权；只算已有结果时不启动训练。

1. 核对数据切分、指标方向、允许研究变量、预算、seed/重复/聚合及选择规则。探索与正式结果分清，Public/Dev 与 Hidden 不混称。执行规则见[公平复验](../../rules/README.md#m03)。
2. 用真实日志检查实现、实际训练量、停止原因与成本。Baseline 有材料可审时直接使用项目方 [autoresearch-baseline-quality](../autoresearch-baseline-quality/SKILL.md)，结论沿用该 Skill 的格式，可并入已有研究/专家说明，不另造审批合同。能提前审的先审，依赖 Reference 的公平性等留到比较后完成；适用项未获证据支持就不冻结。[Baseline 要求](../../rules/README.md#m02)
3. 在授权内运行最小必要实验。正式重复保持独立、完整成对；失败和较差结果保留。训练型每轮保存并干净重载模型，原始日志不改写为摘要。[必要证据](../../rules/README.md#m11)
4. 从原始值复算均值、样本标准差、质量门和改善；审 U 的独立依据及 Reference 未饱和性，不能改 U 制造达标。B/R 和正式评分协议在验证后共同冻结；科学门槛见[评分要求](../../rules/README.md#m04)。
5. 双轨结束后从实际有效结果选唯一 `best_method`，在干净快照按正式协议复验，绑定最终源码与逐次结果。只复验最终方法，不机械给两轨候选各做五次；无提升如实解释，不伪造成功。[最终方法](../../rules/README.md#m10)

已有同协议原始证据足够时直接核对复用；影响科学结果的变更才补相关实验。不影响单次协议/结果时可按空闲 GPU 并行，性能指标受资源竞争影响则独占或串行。产物直接是运行结果、日志、条件性模型和比较结论，不要求先 lock、登记 start/finish 或建立 selection 账本。

需批量执行或复算时使用[独立实验工具](../../docs/experiments.md)：`experiment run` 接受方法、协议和输出目录；`experiment summarize` 只读已有结果。已有入口可直接接入，不必另造调度器。工具的 `COMPLETE` 仅表示声明的结果/证据完整，不等于科学门槛或 Baseline 审查通过；证据不足时保留诊断，不补造数据。
