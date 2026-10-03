# W2：实验与评分工具

当前实现是正式实验记录与数值/证据检查工具。训练、推理及原始指标计算由题目适配层执行；工具根据原始结果复算，不替专家确认方法代表性、训练真实性或 U 的科学依据。科研审查结论与用户冻结确认仍是必要环节。

## 可复用操作

统一入口为 `python3 AutoResearch新流程/cli.py --format json experiment …`，每个命令都显式指定 `--task-root`。题目须已通过 W1 初始化，来源无漂移。

| 操作 | 参数 | 行为 |
|---|---|---|
| `lock` | `--file protocol.json` | 首次正式运行前锁定协议；ID 不覆盖 |
| `extend` | `--protocol p1 --file extra-seeds.json` | 登记追加 seed、理由和时间；保留已有结果，禁止删减或重复 seed |
| `start` | `--file run-spec.json` | 运行前登记角色、seed、方法版本；返回运行绑定哈希 |
| `finish` | `--run-id b-1 --file result-envelope.json` | 保存原始证据索引和结果；无效成功声明保存后立即返回 recorded_invalid |
| `report` | `--protocol p1` | B/R 全 seed 配对、均值、样本标准差、3σ/5σ |
| `report` | `--protocol p1 --role best_method` | 仅汇总唯一最终方法的同协议复验；也可选择 baseline 或 reference |
| `baseline-check` | `--protocol p1 --phase 2 --file review.json` | 核 B01–B08 专家结论、证据与版本；阶段 3 使用 `--phase 3` |
| `score-check` | `--protocol p1 --file score-contract.json` | 复算锚点、分数区间、U 方向与 ceiling，检查 U 论证引用 |

账本存入题目 `.autoresearch-flow/experiments.json`，用文件锁串行化写入，支持不同 GPU 作业并行登记。只读 report 不改状态。协议修订或增加 seed 保留历史，并把已通过的阶段 2 及后续结论标记待重验。

这些工作文件是制作过程的内部格式，最终提交的 `result.json` / `comparison_summary.json` 仍遵从教程；由 W4 进行格式整理和包内路径映射，不要求把账本和额外实验计划全部提交。

## 输入合同

所有 `evidence` 引用采用 `{"path":"题目根内相对路径","sha256":"完整64位哈希"}`。程序核文件存在和真实哈希；方法版本文件应保存于稳定位置，修改后旧实验不能继续引用其旧哈希。

### 正式协议

`protocol.json` 的必填字段：

| 字段 | 要求 |
|---|---|
| `schema_version / id` | `1` / 唯一协议 ID |
| `metric` | `{"name":"本题原始指标","direction":"maximize或minimize"}` |
| `seeds` | 不重复非负整数；训练型或随机任务至少 3 个，声明 high_variance 时至少 5 个 |
| `training / evaluation_mode` | 布尔值 / `random` 或 `deterministic`；零样本方差不自动改变声明 |
| `fixed` | 至少包含 `data / preprocessing / evaluator` 的 SHA-256；可追加必须固定的协议内容指纹 |
| `budget` | 按共同资源口径给各字段 `{"mode":"exact或maximum","value":100,"unit":"steps"}` |
| `rationale` | 预算可比性、确定性/随机性依据；修订时说明原因 |
| `reload_tolerance` | 可选，非负；默认 0，必须在运行前确定 |
| `high_variance` | 可选布尔值，由专家根据探索证据判断，默认 false |

`exact` 表示双方都必须完成的固定量；`maximum` 表示共同上限，合法 early-stop 不要求实际消耗相同。不同硬件时间能否比较仍由 B03 专家审查；不以通用 epochs 门槛判训练不足。

新增 seed 文件为 `{"seeds":[4,5],"reason":"补充重复的具体依据"}`。增加后的全集参与统计，两侧都须补齐；原协议和原运行不被重写，每次运行另绑定当时的 `seed_plan_sha256`。改变方法、数据、预算或指标则用新协议 ID，旧结果保留且不混算。

### 运行登记与结果

`run-spec.json` 包含：

```json
{
  "run_id": "baseline-1",
  "protocol_id": "p1",
  "role": "baseline",
  "seed": 1,
  "method_files": [{"path": "source/baseline/method.py", "sha256": "<真实SHA256>"}]
}
```

角色为 `baseline / reference / best_method`。方法索引应覆盖影响方法结果的源码与配置。同协议同角色必须使用相同方法版本。只有已登记的 `infra_error` 可用 `retry_of` 明确重试；旧失败日志仍参与完整性检查。质量门失败、数值失败等不能被重试字段悄悄隐藏，修正方法后应新建正式组。

题目可信执行入口应产生原始结果文件。W2 的 `result-envelope.json` 携带同样的规范化字段并附证据索引；`evidence.result` 指向独立原始记录，避免自引用哈希。当前适配合同要求原始记录包含 envelope 中除 `evidence` 外的同名字段，程序逐项交叉核对：

- `status`：succeeded / failed / infra_error / hard_gate_failure。
- start 返回的 `seed / role / method_sha256 / protocol_sha256 / seed_plan_sha256`。
- `fixed`：实际使用的数据、预处理和评分实现指纹。
- `raw_metric`：有限原始指标；`quality_passed`：真实质量门结果。
- `actual_budget`：与协议同单位的实际资源量。
- `execution`：command、started_at、finished_at、exit_code；缺项值写 null 并填写 missing_reason，不能从计划或账本时间反推。
- `evidence`：至少 log、result。所有失败也必须保留 log 和清晰 error。
- 训练型成功结果额外需要 `training_origin="initialization"`、reload_passed、reload_metric，以及 model、artifact、reload_log 三个证据引用。artifact JSON 应包含 seed、role、method_sha256、sha256、size_bytes、format、reload_metric，并与模型文件和运行逐项一致。程序不加载模型。
- 原始 NaN/Inf 文件保留为失败证据；账本及 CLI JSON 中将非有限值记为 null，运行不得通过。

真实重训、资源量是否如实、完整依赖索引及重载是否由干净进程完成，需要专家沿日志和执行代码核验。程序不把元数据声明当成真实性证明。

## 统计、评分与审查

PCA 教程“统一术语”明确：默认 Baseline 是未经修改、可运行 Starter 的正式协议结果。若 Starter 只是 Scaffold、不提供 method，则另交可执行的合理朴素 Baseline，并记录源码、入口及与初始方案的映射；评分零点必须来自该正式 Baseline 的真实聚合结果，不得另选更弱锚点。此例外不豁免 B01–B08 的合理性审查。

Public/Dev 与最终 Verifier 必须对齐指标定义、方向与硬约束，但可使用不同数据。各自的协议、聚合结果及锚点来源需明确；不能直接把 Public/Dev 结果称作 Hidden 结果。阶段 3 冻结评分后，还须经目标 Harbor 的独立 Verifier 实际出分；没有官方 Hidden 权限时使用授权同接口数据自验并保留平台待验说明。接口与证据格式见 [PCA 环境合同](PCA_ENVIRONMENT.md)。

report 使用所有正式 seed，不抽样，σ 使用 Baseline 原始指标的样本标准差（n−1）。不足 3σ 或 Δ≤0 阻止通过；3σ–5σ 返回 needs_review，按教程增加重复并标记平台复核；≥5σ 为强数值证据。确定性单次任务的标准差为 null；样本标准差为 0 仍要求 Δ>0。

score-contract 包含 protocol_sha256、upper_bound、metric_ceiling、rationale 和非空 evidence 引用。B/R 从成对结果计算，不接受手填均值。采用 `(raw-B)/(U-B)`，保持连续、单调、方向明确、不裁剪，B→0、U→1；非作弊 Hard Gate 失败返回 0，基础设施错误单独分类。检查 Reference 位于 [0.15,0.8]；headroom <3σ 给专家风险提示，不伪造强制门槛。U 的依据与是否事后反推仍需专家判断。

review.json 绑定 protocol_sha256、experiment_sha256、baseline_method_sha256；阶段 3 再绑定 reference_method_sha256。checks 必须恰含 B01–B08，每项均含 status、reviewer、rationale、非空 evidence。status 为 pass/fail/manual/deferred。只有 B03/B07 的跨方法部分可在阶段 2 deferred，须 current_part_passed=true、due_stage=3、pending_requirement 说明；阶段 3 不再允许 deferred。程序只返回 ready_for_expert_confirmation，不代签合理性或推进阶段。

## 当前实现范围

W2 完成实验与评分的可调用合同。阶段子步骤的推进、用户冻结确认已由 [W5 状态编排](STAGE_STATE.md) 接入；W2 不自行把科学阶段标记为通过。运行环境/凭据由 W3 实现，最终证据格式与独立 QA 交接由 W4 实现，W5 完成操作规范与真实联调。
