你将在当前任务中进行独立方法迭代。先阅读 Harness 提供的 `instruction.md`，明确目标、资源、可修改范围、禁止行为和公开评分规则。TASK_ROOT=/workspace，OUTPUT_DIR=/expert_evidence。

先完整运行未修改的 Baseline（Scaffold 题按题面声明的朴素 Baseline 入口），随后只在题面允许的 `/workspace/solution` 内实现方法，使用真实 Public/Dev 结果比较。公开调用方式：{{PUBLIC_EVALUATION}} 不能读取私有 tests、Reference、Hidden、其他轨迹或专家材料，不能修改可信评测、固定数据或预写评分结果。

每完成一轮，由你向 `/expert_evidence/trajectory.jsonl` 追加八字段对象：`round`（从 1 递增）、`policy_name`、`method_summary`（中文 1–3 句话）、`status`（成功为 ok，失败按真实类型）、`score`（Public/Dev 原始指标，即反馈中的 raw_metric.value，不是归一化 score；未出分为 null）、`failure_reason`（成功为 null，失败写明原因）、`retained_best`（本轮刷新当前最佳时 true，否则 false）、`time`（本轮完成时间 YYYY-MM-DD HH:mm:ss）。如实记录失败；不要增加其他字段、伪造实验或分数。以题面方向判断好坏，原始 error 越低可能越好。

每当得到当前最佳合法方法，将完整代码、入口和配置保存到 `/expert_evidence/best_method/`，不放 checkpoint 或历史方法。输出目录只保存本轨新证据。结束前重新公开评测最佳方法，将其代码、必需模型和配置恢复到 `/workspace/solution`，不能把必需模型遗留在未移交缓存。Agent 结束后由 Harbor 移交候选并调用独立 Verifier，最终 Hidden 不作为本次迭代反馈。

持续进行真实、合法的独立探索。{{DURATION_REQUIREMENT}} 外部异常时保留记录并说明，恢复后在同一会话接续；最终没有提升也要如实保留方法、结果和失败原因。上下文压缩后先核已有任务状态和本组输出，再继续，不读取其他模型的解法。

若评测不能返回可信数值、合法工具不可用或环境异常，报告具体错误及可定位日志，不绕过边界。恢复正常后继续。结束时简述已尝试方向、当前最佳方法、真实 Public/Dev 结果和未解决问题。
