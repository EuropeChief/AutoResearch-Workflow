# 独立材料整理与格式检查

按需要选择三个动作；已有提交包可直接检查。输入是实际文件、已选最佳方法和输出位置，无需初始化题目、阶段登记、选优审批或重新训练。

## 整理 Agent 自写轨迹

```bash
python3 /流程根/cli.py --format json materials trajectory \
  --source /题目根/agent/output/trajectory.jsonl \
  --output /题目根/materials/trajectory_codex.json
```

JSONL 每行一个 Agent 自写轮次，或输入现有含 rounds 的 JSON。程序只包装八字段记录，原文件不覆盖；字段错误时给位置，不补方法、轮次、分数或时间。失败未知分数保留 null，历史最佳标记保留。状态含义不明时提示审阅，不改成成功。

八字段为 round、policy_name、method_summary、status、score、failure_reason、retained_best、time。轮次从 1 严格递增；分数须为有限 Public/Dev 原始指标，时间按教程 YYYY-MM-DD HH:mm:ss 完成时刻。摘要内容、原会话恢复、真实运行与净时长由实际证据核查。

可选 `--metric` 指向实际 `{"direction":"minimize","split":"dev"}`，核历史最佳方向；`--observations` 指向已有逐轮 `{"1":{"raw_value":4.5,"direction":"minimize","split":"dev"}}`，核分数是否与原始评测值一致。没有评测依据就不猜分数单位。翻译、状态或数值修正由制作 Agent 按真实证据完成，原件保留，说明写已有工作记录；不另填修订审批表。

## 按明确来源组包

```bash
python3 /流程根/cli.py --format json materials assemble \
  --sources /题目根/materials-sources.json \
  --best-method /题目根/selected_method \
  --output-dir /题目根/submission
```

来源映射只写“目标包内相对路径 → 实际来源”，相对来源以映射文件所在目录为基准。例如已有标准材料可写：

```json
{
  "workspace": "prepared/workspace",
  "expert_evidence": "prepared/expert_evidence",
  "optimization_evidence": "prepared/optimization_evidence"
}
```

指定的唯一 best_method 放入 expert_evidence/best_method，expert 来源内原有该目录会跳过，避免暗中沿用旧方法。分散材料可逐文件或目录映射，见[来源示例](../templates/materials-sources.example.json)。不重新选优，不要求最终方法有正向改善。来源缺失/映射重叠/原始哈希不符则报错；使用新输出目录，不覆盖来源或已有包。

若来源为独立实验工具的输出，可把其目录直接映射到 optimization_evidence/baseline_runs、reference_runs 或 expert_evidence/best_retest。工具导出当前声明 seed 的逐次结果、日志、方法快照、原始测量和条件性模型，调整为 seed_N/ 布局；保留失败日志，不收实验锁、指纹账本或整个重试树。

元数据中的实际证据 path 会按复制关系转成包内相对路径，并更新此次路径改写产生的元数据哈希。原始哈希须先一致，不“修复”被改动的证据。实际命令/cwd 保留原运行事实；Harbor Trial 原件的配置、结果、reward、日志保留原字节及真实容器路径，不进行统一字符串替换。

来源目录应只含必要材料，工具排除 Git/流程状态/缓存并拒绝明显凭据，不自动判断任意附件的科研用途。方法代码、私有评分和镜像配置不改写。组装后附一份即时格式检查结果；有问题仍保留可检查的输出，依据位置修复，不自动压缩或执行独立 QA。

## 只在包内检查

```bash
python3 /流程根/cli.py --format json materials check \
  --package-root /题目根/submission
```

只读取这个目录；缺引用不会到制作目录补证，不执行候选、Docker、模型重载或 QA Skill。官方随包的只读格式/Docker/NOP 解析器被直接复用。

检查覆盖三目录及必要入口、两轨八字段、annotation/run_summary 核心字段、B/R 十二字段及嵌套类型、seed/role/协议/单位、相对路径与哈希、模型元信息和重载记录、逐 seed 配对统计与评分锚点、题面 seed/提升阈值、同次 NOP 原件。可机械发现的旧题 ID 矛盾、模板来源线索和私有材料混入 Agent 上下文会定位。

最终复验优先识别 expert_evidence 下 role=best_method 的逐次 result.json，核完整同协议 seed 与实际源码。文件清单可直接核绑定；旧哈希算法或只绑定单文件时列出审阅范围，不要求为此改写历史原件。等价的其他证据布局需要明确解释，工具不会假称覆盖。

净时长可读取已有 expert_evidence/timing.json 或 duration_evidence.json 中的 tracks，各轨含原会话标识、活动区间、扣除区间及原始日志引用；区间采用实际观测的数值时间，合并重叠后扣除，比较 run_summary 声明。未识别的外部底座证据保留“需实质审阅”，不猜时长，也不要求用户建立工作流专用账本。7h 资格和真实闭环、任务合法性、叙述及优化面/U 依据由专家结合包内材料核查。

输出 issues 定位文件/字段，notes 提供非阻断整理建议，pending 列仍需实质核查的范围。状态 format_checked_not_qa 只表示覆盖的格式/数值检查通过；存在确定问题时为 issues_found。程序退出码 0/2 分别对应这两种结果，不表示独立质检通过。

[annotation 示例](../templates/expert-annotation.example.json)和[run_summary 示例](../templates/run-summary.example.json)按当前教程字段提供；null 是待填真实数据，不能作为成功结果提交。最终包保留必要证据和当前正确说明，独立 QA 仍由用户在新会话执行；通过后进入后续打包工具。
