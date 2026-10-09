# 模板说明

模板按用途分成两类：

- 新题默认使用 `agent-prompt.zh.md`、`runtime.example.json`、`delivery-form.example.json`、`materials-sources.example.json`、`nop-execution.example.json` 和 `harbor-execution.example.json`；它们只提供输入形状，不自动写入任务状态。
- `confirmation.example.json`、`duration-assessment.example.json`、`expert-annotation.example.json`、`roll-review.example.json`、`run-summary.example.json`、`stage-finish.example.json`、`stability.example.json`、`task-config.example.json` 和 `workflow-policy.example.json` 是历史账本或制作记录模板，供已有旧任务参考，不是新题启动前置。

所有模板都只是示例。填写时以当前 `rules/README.md`、题目教程和质检要求为准；不得把占位值、密钥、作者路径或模板中的示例分数带入正式材料。
