# AutoResearch 工作入口

供专家 Agent（Codex 或 Pi）处理用户指定的题目；生成两条迭代轨迹时使用 Codex。维护流程本身改读 [MAINTAINING.md](MAINTAINING.md)。本分支的工具实现范围见 [README](README.md)，不要把尚未实现的接口当作可运行命令。

## 从实际工作开始

1. 确定用户指定的题目目录和本次目标。已有路径先核对；确实缺少再问，不猜相邻题目，不自动迁移旧任务。
2. 阅读题目已有的一份工作记录及相关真实文件，找出已经完成什么、缺什么、下一步是什么。没有记录时可用一份短 Markdown 记录关键决定、问题、产物路径和下一步；不重复抄录实验数值，不强制文件名，不作为工具参数或最终提交物。
3. 按下面的能力路由继续；只读当前动作相关的[要求](rules/README.md)和原件，不通读全部接口。普通操作在既有授权内连续执行，检查随实际产物和变更触发，不以流程初始化、逐步登记或阶段关闭作为前置。

## 按需要调用能力

| 现在要做什么 | 使用哪个 Skill |
| --- | --- |
| 理解论文、确定优化面、判断 Baseline/Reference 方向 | [研究与设计](skills/autoresearch-research/SKILL.md) |
| 写题面、实现环境/候选接口/可信评分、修复接入 | [任务实现](skills/autoresearch-task-implementation/SKILL.md) |
| 探索实验、锚点标定、Baseline 审查、最终方法复验 | [实验验证](skills/autoresearch-experiment-validation/SKILL.md) |
| 准备/运行/观察双轨、处理外部中断、保存运行依据 | [Agent 迭代](skills/autoresearch-agent-iteration/SKILL.md) |
| 整理轨迹与材料、处理独立 QA 反馈、通过后打包 | [材料与交付](skills/autoresearch-delivery/SKILL.md) |

不知道从哪里继续时看[六阶段导航](docs/stages.md)。能力可以跨阶段使用；局部返修、现成材料整理或 QA 后打包直接进入相应能力，不补办前面阶段的手续。

指定旧题返修时，先保留原包、原版本和报告，按当前规则列差异，再进入受影响能力修复与复验。文案/格式不自动重跑研究，方法、评分、部署或版本对应改变则核实际影响；旧 PASS 不直接沿用，历史缺指纹只在原快照与运行对应可证明时补算。记录复用已有短工作记录，不新增返修账本。

进入某一阶段时，先打开 `rules/stages/stage-<阶段>-*.md` 获取当前行动、证据和阶段门提示；阶段 1 先运行 `python -m autoresearch_flow.task_workspace --task-root <题目根> status`，确认 Git 范围，再按需执行 `init-git`、`preview` 和显式检查点。关键决定追加到题目 `.autoresearch/decision-log.md`，格式参考 `templates/decision-log.example.md`。流程维护者用 `python tools/build_stage_views.py --check` 做包内一致性检查。视图只是规则正文的导航，不是题目状态账本。

进入阶段、阶段门/高成本动作前及影响性修改后，用 `python cli.py --format json preflight --task-root <题目根> --stage <1..6>`；动作前加 `--before`，退出加 `--phase exit`。引用已有检查/审查，不新建逐条 PASS 账本；具体输入、到期与例外口径见[阶段预检](docs/preflight.md)。

只有研究合同、评分锚点冻结、正式双轨启动需专家明确确认。检查就绪后提交一个简短决定请求，收到答复才按预检 `proposal` 追加确认记录；未变的已有批准直接复用，机器 PASS 不等于批准。普通准备、故障恢复和独立 QA 后打包不增加审批；已完成题目的局部返修不追补历史手续。

权威顺序与当前版本统一在[要求入口](rules/README.md)。关键科学结论用代码和实验支撑，未检查不能写通过；来源冲突、范围改变或需要新资源授权时提交具体问题，不反复询问已确认决定。最终 QA 由用户在独立会话进行，取证边界仅为指定最终包。
