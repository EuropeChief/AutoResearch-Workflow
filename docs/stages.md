# 六阶段工作导航

这是定位工作用的地图，不是状态机。根据已有证据接续、按实际问题回到相关能力；不逐阶段登记、签字或关闭，只保留研究合同、锚点冻结和双轨启动三个专家决定。规则只在[当前要求](../rules/README.md)维护，下面不再复制一套。

当前阶段的行动、所需证据、前置引用和阶段门提示由 [`rules/stage_matrix.json`](../rules/stage_matrix.json) 提供；对应的六份阅读视图在 [`rules/stages/`](../rules/stages/)。视图是矩阵的派生物，流程维护时可运行 `python tools/build_stage_views.py --check` 检查正文、矩阵和视图是否漂移。

| 阶段 | 有意义的子步骤 | 已完成的依据 | 使用能力 |
| --- | --- | --- | --- |
| 1. 研究与选题 | Git 预检/起始检查点 → 理解论文与代码 → 比较方法空间 → 最小可行性探索 → 提出 B/R 方向 | 题目仓库范围和忽略规则已核对；允许面、固定面、资源可行性和待验证假设明确；此时只是方向，不冻结锚点 | [研究](../skills/autoresearch-research/SKILL.md) |
| 2. 环境与 Baseline | 明确题面/接口 → 构建公开及私有环境 → 跑通 Baseline → 审查健全性与代表性 | 真实调用和反馈可用，Baseline 有证据支持；依赖 R 或后续运行的判断保持待验证 | [实现](../skills/autoresearch-task-implementation/SKILL.md)、[实验](../skills/autoresearch-experiment-validation/SKILL.md) |
| 3. Reference 与标定 | 实现合法改进 → 同协议正式复验 → 统计/质量门/U 分析 → 共同冻结 B/R/评分协议 | Baseline 合理、Reference 可复现且提升充分、锚点有依据；问题未解决就继续研究，不改数字造通过 | [实现](../skills/autoresearch-task-implementation/SKILL.md)、[实验](../skills/autoresearch-experiment-validation/SKILL.md)、[研究](../skills/autoresearch-research/SKILL.md) |
| 4. 双 Agent 迭代 | 适用时长与运行配置 → 最小预检 → 两轨独立运行/观察/原会话恢复 → 各自收口 | 两条真实轨迹、候选及日志和净时长依据；不以是否提升单独判定有效性 | [迭代](../skills/autoresearch-agent-iteration/SKILL.md) |
| 5. 最佳方法复验 | 比较有效结果 → 选唯一 best_method → 干净快照同协议复验 | 最终源码与逐次结果绑定、可重跑；不默认给两候选各做一套正式复验 | [实验](../skills/autoresearch-experiment-validation/SKILL.md) |
| 6. 材料与交付 | 整理/格式核对 → 用户独立 QA → 有影响的返修及复核 → 通过后压缩与填表 | 指定最终包、完整独立通过报告、三个附件及七项填表信息 | [交付](../skills/autoresearch-delivery/SKILL.md) |

程序适合核字段、数值、路径和调用结果；优化面、Baseline 代表性、U 依据等需要 Agent 沿真实证据判断。结论直接写进已有研究记录、训练证据说明或专家说明，不为同一事实新建签署报告。

阶段入口、动作前与退出时使用[只读预检](preflight.md)，分别定位准备缺口、到期阻断和结果缺口；例外以专家确认为准。修改有实质影响时列出定向复核范围，不自动重开阶段或重跑双轨。只打包已通过独立 QA 的材料仍直接使用打包工具。

阶段 1 研究最小包完成后请求 `research_contract` 确认，阶段 3 证据满足后请求 `anchor_freeze`，阶段 4 正式启动前请求 `dual_track_launch`。确认绑定已有文件，实际答复后才追加决定；阶段 2 沿用研究确认、不新增实现审批，阶段 5/6 不追补前三项手续。预检不会启动任务，也不会在健康轨迹运行中自动暂停。

## 非从零开始时

- **只修一个问题**：读报告和受影响文件，修复并做相关核验；仅对受影响的方法、协议或运行证据补验。
- **只有现成材料要整理**：直接使用交付能力；缺失证据据实标出，不初始化实验账本或重跑完好实验。
- **QA 已通过，只需附件**：核报告完整且对应指定包，直接三包压缩；不要求再审优化面、关闭阶段或绑定 QA 状态。
- **接续研究或实验**：用短工作记录和实际结果确认位置；旧版任务须由用户明确指定处理范围，不自动升级原运行底座。
