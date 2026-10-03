# 冻结时长与非训练 7h 例外

默认各轨 10h；政策修订以 `task policy` 返回为准。时长快照随任务冻结，最终提交 JSON Schema 不因此改变。

## 规则依据与分阶段验收

教程 PCA 版 L565–585、L809–827，规则 AR-038/044：默认每组独立不少于10小时。仅任务完全不训练/不微调、单轮迭代很短、可持续 Roll 时允许每组不少于7小时。两个模型的时长不能相加，排队、安装、构建故障和长时间阻塞不计有效时间。不额外规定统一“单轮小于几分钟”的阈值。

| 时点 | 要确认的内容 | 尚不能宣布完成的内容 |
|---|---|---|
| 4.1、runtime prepare 之前 | 正式协议是非训练；专家确认全任务不微调；已有短迭代实测证据、选择理由和确认人 | 正式双轨时长、闭环、最终方法干净重跑 |
| 4.4 | 两个不同会话各达冻结净时长；每条至少3轮方法闭环；连续演进；结束时至少一个可验证方向 | 尚未进行的阶段5干净重跑 |
| 5.3/5.4 | 唯一最终方法按冻结协议复验且干净快照重跑成功 | 平台最终验收 |
| 6 | 包内证据支持上述事实；专家说明与run_summary一致 | 不以本地合同测试代替独立QA |

不满足条件时保持10h；不能因为运行不足10h而事后改名7h。7h仍不要求最终必须提升，但失败须真实，纯排障或机械重复不算有效方法闭环。

## 1. 启动前选择

默认10h无需手工改配置。阶段4.1由专家评估；没有充分依据就继续默认10h。旧状态使用其原版本处理；本版只接受新任务和同版本恢复。

合格例外复制并填写 [资格决策模板](../../templates/duration-assessment.example.json)。模板空值、REPLACE和示例文字不是证据。`evidence`支撑资格与选择理由；`iteration_samples`提供真实单轮秒数与原始记录；`protocol_id`须指已锁定、`training=false` 的正式协议。专家须核“非训练”覆盖整个任务，不只看某个评分脚本是否训练。

```bash
python3 "$FLOW_ROOT/cli.py" --format json task policy --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" task duration-set --task-root "$TASK_ROOT" \
  --file "$TASK_ROOT/evidence/duration-assessment.json" --confirm-duration
```

`--confirm-duration`只在已有明确确认下传入。命令要求处于4.1、runtime尚未准备，记录确认时间、决定/证据/正式协议指纹并冻结；不能覆盖已有决定。训练协议、缺样本、缺资格或无确认均拒绝。也可用 `mode=default_10h` 加 reviewer/approved_by/rationale/evidence 记录明确维持默认的决定。

准备 runtime 后不允许更改时长；不要删除runtime或历史决策来绕过。已冻结的时长不得被后续操作静默覆盖。

## 2. 准备、运行与恢复

以 [中文Prompt模板](../../templates/agent-prompt.zh.md) 为基础保留 `{{DURATION_REQUIREMENT}}`。`runtime prepare`会将其渲染成当前冻结要求，两组共用；7h模板若残留10h指令会拒绝。不要直接把未渲染模板交给迭代Agent，使用runtime保存的prompt.md。

两轨state与runtime manifest记录同一时长快照指纹；每次加载都检查资格原证据及快照一致性。不能用旧 runtime 代替本版正式准备与冻结。初始Prompt、同会话继续指令、监督循环、status、Harbor收口、交付工具时长核验均读取同一政策。不会把7h或10h当作本次墙钟预算，也不改变正常成本确认/暂停/故障扣除机制。

恢复只用原会话。若资格/原证据漂移，停止并查明原因；不是创建新会话拼时长的理由。预检用独立会话和时间，不算正式轨迹。

## 3. 结束后的闭环审阅

先按交付工具整理Agent自写轨迹，根rounds及每轮八字段保持不变。7h任务的现有 `delivery trajectory-review` 输入额外填写 [闭环审阅模板](../../templates/roll-review.example.json) 中的内容（专家内部审阅，不是往轨迹加字段）：

- 每轮 `method_iteration` 指明是否真实方法迭代；纯排障/机械重复填false，不删除其真实轨迹。
- 有效轮次说明实际 `method_change`、`score_conclusion`、`next_decision`，给出原始操作/评分日志位置，`public_dev_protocol`与启动前一致。
- 每条至少3个非重复有效闭环；真实方法失败可计，但不能虚构评分或把环境问题标为方法结果。
- 整条填写 `continuous_evolution`、`next_direction`、`typical_round_minutes`。审阅条目覆盖全部实际轮次，不只列成功轮。

程序核数量、完整性、引用和绑定；语义是否真实、是否非法操作、是否确实很短仍由专家沿证据核对，不能把字段齐全当作科研结论。

阶段4无需先提交未来的最佳方法干净重跑。阶段5仍用原有唯一best_method复验与clean_result/clean_log接口，未完成则不能组包。

## 4. 摘要和最终包

`run_summary.json`字段不增减。两行agent_execution按既有codex、seed顺序填写实际duration_hours、有效闭环轮数、典型分钟数；只在资格与后验条件齐备时把例外的used/non_training/short_iterations/rollable_proved设为true。`evidence`先写真实理由；组包会追加证据一致的详情。禁止向上凑到7h，数值填写到足以对应净秒数的精度。

例外包由 `delivery build` 从已核资料生成：

- `expert_evidence/duration_evidence.json`：冻结资格、双轨独立标识、可重算活动/扣除区间、逐轮闭环、干净重跑及源码绑定。
- `expert_evidence/duration_sources/`：上述事实必要的原始引用（资格、方法/评分/计时日志、干净重跑结果），按内容哈希复用相同文件；不复制鉴权或其他题目材料。与所有导出日志一样，提交前检查是否含敏感数据。
- 在专家说明末尾和run_summary的原evidence字符串内追加同一份中文事实说明，不改原始轨迹/源文档，不添run_summary字段。

这些是证明例外的本流程支撑文件，不声称教程要求使用这两个固定文件名；默认10h包不额外生成。完整包检查只读包内文件，校验每轨净时长、轮次/典型耗时、当前轨迹与最佳方法、干净重跑、非训练协议和两份说明一致性。不能用几项true、外部工作目录文件或两条时长相加替代证据。

验收能力与未覆盖范围见 [发布状态](../../RELEASE.md)。
