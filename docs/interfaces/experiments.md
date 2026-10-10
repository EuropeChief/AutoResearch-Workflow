# 实验与评分工具（历史账本接口）

> 本页的 `task-root`、lock/report/execute 等命令只服务历史任务。新题使用[独立实验接口](../experiments.md)的 `experiment run/summarize`，不初始化状态账本。

当前实现是正式实验记录与数值/证据检查工具。训练、推理及原始指标计算由题目适配层执行；工具根据原始结果复算，不替专家确认方法代表性、训练真实性或 U 的科学依据。科研审查结论与用户冻结确认仍是必要环节。

## 可复用操作

统一入口为 `python3 "$FLOW_ROOT/cli.py" --format json experiment …`，每个命令都显式指定 `--task-root`。题目须已通过 状态工具 初始化，来源无漂移。

| 操作 | 参数 | 行为 |
|---|---|---|
| `lock` | `--file protocol.json` | 首次正式运行前锁定协议；ID 不覆盖 |
| `extend` | `--protocol p1 --file extra-seeds.json` | 登记追加 seed、理由和时间；保留已有结果，禁止删减或重复 seed |
| `start` | `--file run-spec.json` | 运行前登记角色、seed、方法版本；返回运行绑定哈希 |
| `finish` | `--run-id b-1 --file result-envelope.json` | 保存原始证据索引和结果；无效成功声明保存后立即返回 recorded_invalid |
| `report` | `--protocol p1` | B/R 全 seed 配对、均值、样本标准差、3σ/5σ |
| `report` | `--protocol p1 --role best_method` | 仅汇总唯一最终方法的同协议复验；也可选择 baseline 或 reference |
| `execute` | `--plan retest-plan.json` | 执行已选唯一最终方法的有限本地队列，直接复用 start/finish/report；不是新的评分入口 |
| `baseline-check` | `--protocol p1 --phase 2 --file review.json` | 核 B01–B08 专家结论、证据与版本；阶段 3 使用 `--phase 3` |
| `score-check` | `--protocol p1 --file score-contract.json` | 复算锚点、分数区间、U 方向与 ceiling，检查 U 论证引用 |

账本存入题目 `.autoresearch-flow/experiments.json`，用文件锁串行化写入，支持不同 GPU 作业并行登记。只读 report 不改状态。协议修订或增加 seed 保留历史，并把已通过的阶段 2 及后续结论标记待重验。

这些工作文件是制作过程的内部格式，最终提交的 `result.json` / `comparison_summary.json` 仍遵从教程；由交付工具进行格式整理和包内路径映射，不要求把账本和额外实验计划全部提交。

## 输入合同

所有 `evidence` 引用采用 `{"path":"题目根内相对路径","sha256":"完整64位哈希"}`。程序核文件存在和真实哈希；方法版本文件应保存于稳定位置，修改后旧实验不能继续引用其旧哈希。

### 正式协议

`protocol.json` 的必填字段：

| 字段 | 要求 |
|---|---|
| `schema_version / id` | `1` / 唯一协议 ID |
| `metric` | `{"name":"本题原始指标","direction":"maximize或minimize"}` |
| `split` | 正式交付必填的数据划分名称（如 `dev`），与实际 `fixed.data` 对应；锁定后不可从标注文件补写或改名。未填写的探索协议不能直接用于最终组包 |
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

题目可信执行入口应产生原始结果文件。实验工具 的 `result-envelope.json` 携带同样的规范化字段并附证据索引；`evidence.result` 指向独立原始记录，避免自引用哈希。当前适配合同要求原始记录包含 envelope 中除 `evidence` 外的同名字段，程序逐项交叉核对：

- `status`：succeeded / hard_gate_failure / format_error / timeout / resource_exceeded / infra_error / failed。已知失败按类型登记；failed 用于其他未细分失败，不代替已知分类。除 succeeded 外均不进入正常聚合，CLI 返回非零退出码；只有 infra_error 允许显式登记基础设施重试。
- start 返回的 `seed / role / method_sha256 / protocol_sha256 / seed_plan_sha256`。
- `fixed`：实际使用的数据、预处理和评分实现指纹。
- `raw_metric`：有限原始指标；`quality_passed`：真实质量门结果。
- `actual_budget`：与协议同单位的实际资源量。
- `execution`：command、started_at、finished_at、exit_code；缺项值写 null 并填写 missing_reason，不能从计划或账本时间反推。
- `evidence`：至少 log、result。所有失败也必须保留 log 和清晰 error。
- 训练型成功结果额外需要 `training_origin="initialization"`、reload_passed、reload_metric，以及 model、artifact、reload_log 三个证据引用。artifact JSON 应包含 seed、role、method_sha256、sha256、size_bytes、format、reload_metric，并与模型文件和运行逐项一致。程序不加载模型。
- 原始 NaN/Inf 文件保留为失败证据；账本及 CLI JSON 中将非有限值记为 null，运行不得通过。

真实重训、资源量是否如实、完整依赖索引及重载是否由干净进程完成，需要专家沿日志和执行代码核验。程序不把元数据声明当成真实性证明。

### 最终方法的本地复验队列

前提：已 `delivery best-select`，已锁定正式协议和全部 seed，用户明确授权所用资源。此入口运行**专家维护的可信评测适配器**，不替代 Harbor、独立 Verifier 或候选隔离；不得直接在宿主机执行未经隔离的 Agent 源码。适配器负责调用本题已有可信评测路径，原样落实协议及设备限制；本队列只管调度和证据。

`retest-plan.json` 示例（占位哈希和路径须由当前任务实际索引替换）：

```json
{
  "schema_version": 1,
  "id": "final-retest",
  "protocol_id": "p1",
  "seeds": [1, 2, 3, 4, 5],
  "selection": {"path": ".autoresearch-flow/delivery/best_versions/<版本>/selection.json", "sha256": "<真实哈希>"},
  "adapter_files": [{"path": "evaluation/retest_adapter.py", "sha256": "<真实哈希>"}],
  "command": ["python3", "{adapter_root}/evaluation/retest_adapter.py", "{request}"],
  "output_root": "retests/final",
  "timeout_seconds": 7200,
  "resources": {
    "gpu_ids": ["4", "6"], "gpus_per_run": 1, "max_parallel": 2, "cpu_threads": 4,
    "metric_sensitive": false, "hardware_sensitive": true,
    "authorization": {"path": "records/retest-resource-approval.md", "sha256": "<真实哈希>"}
  }
}
```

- `seeds` 必须等于协议全集，不因示例固定为 5；`timeout_seconds` 是本次计划的**单 seed** 上限，示例不是通用预算规定。CPU 使用 `gpu_ids=[] / gpus_per_run=0`。授权文件保留真实允许的卡、并发和适用范围，程序核引用，不替用户授予资源权限。
- `adapter_files` 包含影响执行的全部适配器源码与配置。队列复制适配器和当前最终方法到各 seed 的独立目录；新进程、独立工作目录、原始 seed 和 `PYTHONHASHSEED`（取 32 位）分开记录，不共享本题已训练终态。适配器仍须显式设置 Python/NumPy/框架 RNG，并遵守 `training_origin=initialization`；环境变量本身不能证明训练独立。
- 命令是 argv，只有 `{adapter_root}`、`{request}` 两个替换变量，不使用 shell。request 包含实验工具`run` 绑定、完整 `protocol`、方法/输出目录、分配设备、源码副本哈希和计划指纹。适配器必须同步等待全部子作业完成，不得启动脱离监督的后台作业；Docker/Harbor 适配器也必须在超时或信号中断时清理**自己的**容器。
- 适配器写 `adapter-result.json`：沿用上述实验工具结果字段（execution 由监督器实际观测补入），额外写 `devices`，CPU 为 `["cpu"]`、GPU 为实际使用的 UUID 列表。GPU 适配器应实际检查可见设备与 CUDA 运算，并将分配 UUID 显式传给 Docker/Harbor，不能认为宿主 `CUDA_VISIBLE_DEVICES` 会自动配置容器。训练型增加 `artifacts={"model":"model.bin","artifact":"artifact.json","reload_log":"reload.log"}`，均为本次目录内相对路径。适配器声明不替代专家沿运行日志的真实性检查。
- GPU 只从授权列表中选择无观测计算作业的设备；同用户队列用设备锁避免同卡重叠，忙卡不抢占。硬件敏感时限制同型号/驱动并冻结实际 UUID；时延/吞吐敏感时要求串行，并由专家落实外部争用控制。本地观察与互斥不等同于独占共享服务器。CPU 线程数、每次 GPU 数、协议 batch/步数/数据/精度/评分不得为了并行而更改。

在流程根执行：

```bash
python3 cli.py --format json experiment execute --task-root <题目目录> --plan <计划文件>
python3 cli.py --format json experiment report --task-root <题目目录> --protocol p1 --role best_method
```

长任务可在专家的 tmux 中前台运行。卡忙且没有本队列活跃进程时返回 `waiting_for_resources` 和待执行 seed，稍后用**同一命令、同一计划**继续；`running` 表示发现上次监督进程遗留的活跃作业，绝不重复启动。完成由账本全 seed 检查决定，不看某时刻 GPU 空闲。

每个正常启动的 seed 保留 `launch-intent.json`、`request.json`、`run.log`、实际 `execution.json`、未经改写的 `adapter-result.json`、规范化 `result.receipt.json`、用于断点入账的 `ledger-result.json` 及训练附件；启动前中断时不补造尚未产生的请求或结果。恢复先对齐启动意图和实验工具账本，避免两者写入之间中断后遗漏运行。退出码不可得时如实记 null，不从结果文件推断成功；日志和原结果不覆盖。启动失败或监督进程丢失状态记 `infra_error`；非零方法退出记 failed、超时记 timeout、输出错误记 format_error，均不进入均值。只有已入账的基础设施失败可显式 `--retry-infra <run_id>`，旧尝试保留；适配器不能自行把方法失败标为可重试 infra_error。其他真实外部异常需专家给出证据按既有实验工具手动登记流程处理，不由错误字符串猜测。

这些内部工作文件按证明需要整理，不要求整套队列目录进入提交包。CPU 实进程和模拟设备合同测试已覆盖队列行为；真实 GPU 小探针尚待独立授权与动态验收，不以离线测试宣称已通过。

## 统计、评分与审查

PCA 教程“统一术语”明确：默认 Baseline 是未经修改、可运行 Starter 的正式协议结果。若 Starter 只是 Scaffold、不提供 method，则另交可执行的合理朴素 Baseline，并记录源码、入口及与初始方案的映射；评分零点必须来自该正式 Baseline 的真实聚合结果，不得另选更弱锚点。此例外不豁免 B01–B08 的合理性审查。

Public/Dev 与最终 Verifier 必须对齐指标定义、方向与硬约束，但可使用不同数据。各自的协议、聚合结果及锚点来源需明确；不能直接把 Public/Dev 结果称作 Hidden 结果。阶段 3 冻结评分后，还须经目标 Harbor 的独立 Verifier 实际出分；没有官方 Hidden 权限时使用授权同接口数据自验并保留平台待验说明。接口与证据格式见 [PCA 环境合同](environment.md)。

report 使用所有正式 seed，不抽样，σ 使用 Baseline 原始指标的样本标准差（n−1）。不足 3σ 或 Δ≤0 阻止通过；3σ–5σ 返回 needs_review，按教程增加重复并标记平台复核；≥5σ 为强数值证据。确定性单次任务的标准差为 null；样本标准差为 0 仍要求 Δ>0。

score-contract 包含 protocol_sha256、upper_bound、metric_ceiling、rationale 和非空 evidence 引用。B/R 从成对结果计算，不接受手填均值。采用 `(raw-B)/(U-B)`，保持连续、单调、方向明确、不裁剪，B→0、U→1；非作弊 Hard Gate 失败返回 -1，按 hard_gate_failure 状态排除，不参与正常方案排序或聚合。正常方案的公式结果即使恰为 -1 或小于 -1 仍合法，不能仅凭分数判断有效性。格式错误、超时、资源超限和基础设施错误分别返回对应失败类型与清晰、可操作的 error，不统一折成 -1 或 0；账本保留失败原件，不替失败伪造正常分数。检查 Reference 位于 [0.15,0.8]；headroom <3σ 给专家风险提示，不伪造强制门槛。U 的依据与是否事后反推仍需专家判断。

review.json 绑定 protocol_sha256、experiment_sha256、baseline_method_sha256；阶段 3 再绑定 reference_method_sha256。checks 必须恰含 B01–B08，每项均含 status、reviewer、rationale、非空 evidence。status 为 pass/fail/manual/deferred。只有 B03/B07 的跨方法部分可在阶段 2 deferred，须 current_part_passed=true、due_stage=3、pending_requirement 说明；阶段 3 不再允许 deferred。程序只返回 ready_for_expert_confirmation，不代签合理性或推进阶段。

阶段推进和用户冻结确认通过 [状态登记](state.md) 完成；实验账本与数值检查不会自行批准科学结论。
