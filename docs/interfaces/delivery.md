# 轨迹证据、唯一最佳方法和最终包（历史交付接口）

> 本页保留旧题交付账本命令。新题优先使用[材料接口](../materials.md)和[直接打包](../packaging.md)，不初始化任务状态或生成审批收据。

整理 Agent 自写轨迹、选定唯一方法、绑定复验，组装最终包并接收独立 QA。程序检查格式与证据绑定，不代替方法审查或项目方验收。

## 边界

- 两条正式 Codex 轨迹的 Agent **在迭代过程中自行写**各自 `formal/output/trajectory.jsonl`。交付工具 只核验、必要时有据修订，再生成最终 `trajectory_codex.json`、`trajectory_seed.json`。运行底座 原始日志用于逐轮交叉审阅，不用来凭空生成缺失摘要。
- 默认两条轨迹各须有不少于10小时的可核净有效时长；启动前冻结的非训练7h例外另按 [时长政策](duration.md) 核全部条件。中断恢复和排除异常时间沿用运行底座台账。交付工具 不把程序判断冒充专家对方法内容、合规性或研究价值的裁定。
- 仅正式唯一 `best_method/` 做实验工具同协议完整 seed 复验及干净快照重跑。Baseline/Reference 的正式多 seed 原始证据由题目方提供到 `optimization_evidence/`，交付工具 不重新训练。
- 组包器生成 `workspace/`、`expert_evidence/`、`optimization_evidence/` 三个顶层目录。检查器允许有用额外材料，给出格式观察，由独立 QA 按内容分类；不因多交自动失败。制作期原始日志、版本快照、修订审计及 QA 绑定记录留在 `.autoresearch-flow/delivery/`，不混入提交包。缺少包内必交证据不得用包外草稿补救。
- 独立质检由用户在**新会话**对指定最终包运行；本工具只生成准确交接路径、绑定报告与包版本，不调用质检 Skill，也不声称平台审核通过。

## 顺序与命令

统一入口：`python3 "$FLOW_ROOT/cli.py" --format json delivery ...`。以下命令均需显式指定任务根；`delivery check` 例外，只取证最终包。

1. `trajectory-finalize --task-root TASK --track codex|seed [--file CORRECTIONS.json]`：读取 Agent 自写 JSONL，每行恰好为 PCA 八字段，轮次从 1 连续。score 为真实 Public/Dev 原始指标，不是归一化分数。允许用 `--file` 提供有原行哈希、理由和证据的逐行修订；原件和最终版保留。缺失事实不可从日志猜写。
2. `trajectory-review --task-root TASK --track codex|seed --file REVIEW.json`：专家按每轮摘要核对可定位的真实操作/评分记录，填 `consistent: true` 才能进入组包。工具只验记录、引用与哈希，`consistent` 的事实判断由专家承担。
3. `best-select --task-root TASK --file SELECTION.json`：比较两组有效 Public/Dev 评分，快照唯一最终源码。若两组都没有正向合法方法，未修改 Starter 仅在当期权威原文与已有明确授权允许时采用，并解释来源和未提升原因；不得默认为最佳 Agent 方法。
4. `best-verify --task-root TASK --file VERIFICATION.json`：该源码哈希须与实验工具`best_method` 正式 seed 复验完全一致，并提交干净任务快照重跑结果、日志、命令、起止时间、退出码与专家结论。可先使用 [实验工具 本地复验队列](experiments.md#最终方法的本地复验队列) 按明确授权资源串行或并行执行；队列完成不代替本步核验。
5. `build --task-root TASK --file PACKAGE.json`：复制明确来源、生成不可混入制作日志的版本目录；先做结构/字段/引用及 B/R/U 线性归一化检查，再绑定 B/R 正式逐次原始 result 哈希与同协议均值、两组有效时长及唯一方法复验。输出 `package_path` 与 `package_sha256`。
6. `check --package-root PACKAGE`：**只读取提交包内部**的格式和必要文件；结果 `format_checked_not_qa` 不代表正式 QA。
7. `qa-handoff --task-root TASK --package-root PACKAGE`：生成独立新会话使用的准确路径与快照哈希；用户手动运行只读质检，QA 前不正式压缩。
8. `qa-bind --task-root TASK --package-root PACKAGE --report REPORT.json`：绑定机器可读报告，状态为 `attached_unreviewed`。若 QA 在另一目录扫描，程序核完整相对路径、内容和权限与本包相同，不修改原报告；扫描目录须仍可读取。当前会话逐项审阅报告并返修，新包须重新独立质检。
9. `archive --task-root TASK --package-root PACKAGE --name semantic-benchmark [--file CHECKS.json] [--max-part-bytes N]`：命令入口核当前独立 QA 已完成且 PASS、处置无未解决项、包内教程自验证据齐全，再生成三份 ZIP。`CHECKS.json` 是 6.5 的 `checks` 对象（非整个步骤记录）；省略项只复用先前有效登记，缺证拒绝。完整包外层用语义化英文名，不含题号；另两包只取该最终包中的 `workspace/harbor_task/`、`optimization_evidence/`。保留中文 UTF-8 名称和 Unix 权限。超过 **300,000,000 字节**才分卷，默认每卷最多 **290,000,000 字节**；完整 ZIP 仍保留。输出目录在 `.autoresearch-flow/delivery/archives/`，内含三包、所需分卷、`archives.json`、`SHA256SUMS.txt` 和 `上传说明.md`。每包流式解压核 CRC/路径/内容/权限，每卷核大小和按编号字节拼接哈希；分卷不是可单独解压的 ZIP。
10. `form --task-root TASK --package-root PACKAGE --file FORM.json`：三包核验后，在同一输出目录生成 `填表信息.md` 和包外绑定 `form.json`。按[模板](../../templates/delivery-form.example.json)提供四段有包内源码/说明依据的中文概述；Baseline/Reference 原始均值、归一化分数、方向、split 和次数从当前包读取，不能填 Agent 最佳分数替代 Reference。程序核来源与数值，责任 Agent/专家核方法叙述，不编造未做的试跑；人工改过的文件不会静默覆盖。

6.5 的进度为 `qa_verified → archives_verified → form_ready`。`stage check` 可报告中间进度，但只有三者闭合才能登记 6.5 `passed` 并 `finish 6`，压缩本身不依赖先完成阶段 6。任何加删文件、内容或权限变化使旧 QA/归档绑定失效。对不影响方法的说明修订不要求重跑训练，但修订后的最终包仍须新会话 QA。重打包生成新的外部版本绑定，不向被 QA 接受的源包加文件。

普通路径的 `checks.nop_execution` 引用必要 NOP 原件索引 JSON；6.2/6.5 指向最终包 `expert_evidence/`，2.1/3.5/4.1 指向制作目录。新题缺证正常阻断；指定旧题绑定[官方成对结果](../legacy-qa.md)后不重复要求已豁免的历史材料。已交索引中 `trial_files` 和 `trial_task_binding.evidence` 相对于当时的 `--task-root`；建议原件放在题目根 `expert_evidence/`，以 `support_files` 原相对路径复制进最终包。实际路径改变应更新引用，最终包只读包内原件，不从制作目录补读。

## 输入 JSON 的最小形状

`CORRECTIONS.json`：

```json
{"source_sha256":"<Agent 原始 JSONL SHA-256>","corrections":[{"line":1,"raw_sha256":"<原行不含换行的 SHA-256>","replacement":{"round":1,"policy_name":"实际方法名","method_summary":"有据修正后的摘要","status":"ok","score":4.5,"failure_reason":null,"retained_best":true,"time":"2026-09-30 10:00:00"},"reason":"修订理由","evidence":[{"path":"<任务内相对路径>","sha256":"<证据 SHA-256>"}]}]}
```

无修订时省略 `--file`。修订允许修格式、编号或有原始依据的表述，不允许捏造方法或结果。

示例分数/时间不是真实证据，不可照抄。status 成功为 ok，失败按真实类型；无分用 null，失败不能标 retained_best=true。该布尔值按每轮当时保留决策记账，不事后抹去历史最佳。专家审阅仍须核原始分数、切分、时间、摘要和方法对应，格式通过不代表事实正确。

`REVIEW.json`：

```json
{"reviewer":"<专家>","rounds":[{"round":1,"consistent":true,"evidence":[{"ref":{"path":"<任务内正式日志或评分记录>","sha256":"<SHA-256>"},"locator":"<具体行号、事件 ID 或评分 ID>"}]}]}
```

`SELECTION.json`：

```json
{"selected_track":"seed","rationale":"同一 Public/Dev 口径的最高有效分","candidate_results":{"codex":{"result":{"path":"<结果 JSON>","sha256":"<SHA-256>"}},"seed":{"result":{"path":"<结果 JSON>","sha256":"<SHA-256>"}}}}
```

不能评分的候选将其 `result` 设为 `null`，并给 `invalid_reason` 和非空 `evidence`。选择 Starter 时另须 `starter_directory`、`starter_exception:{reviewer,rationale,evidence}`。

`VERIFICATION.json`：

```json
{"protocol_id":"<实验工具 正式协议 ID>","clean_result":{"path":"<成功重跑 result.json>","sha256":"<SHA-256>"},"clean_log":{"path":"<重跑日志>","sha256":"<SHA-256>"},"reviewer":"<专家>","rationale":"干净快照重跑、方法哈希和结果一致"}
```

重跑结果须含 `status=succeeded`、`method_sha256`、有限 `score`，以及 `execution:{command,started_at,finished_at,exit_code:0}`。

`PACKAGE.json`：

```json
{"protocol_id":"<实验工具 正式协议 ID>","workspace_directory":"<任务内待交 workspace 相对目录>","optimization_directory":"<任务内待交 optimization_evidence 相对目录>","expert_document":{"path":"<专家作业说明文档>","sha256":"<SHA-256>"},"expert_annotation":{"path":"<expert_annotation.json>","sha256":"<SHA-256>"},"run_summary":{"path":"<run_summary.json>","sha256":"<SHA-256>"}}
```

上述制作期引用使用**任务根内相对路径和 SHA-256**；`FORM.json` 各段 `sources` 特别使用**最终包根内**相对路径，其 `checks` 仍用任务根。训练型任务的模型、日志、checkpoint 按教程保留。构建时从实验工具补入 `comparison_summary.evaluation_protocol` 和 `formal_aggregates`（正式 B/R 均值、次数、seeds 及评分口径），供包内填表取证；不以包外报告补缺。非训练任务不强制模型；确定性单次评估、固定模型随机评估和逐seed训练按[当前实验口径](../experiments.md)及冻结协议处理。专家文件仍按当期教程填写；工具只核机械可判断的字段与台账一致性。

## 验收边界

环境按[当前 Harbor 接口](../harbor.md)核实际镜像复用或独立构建分支，不强制每题两个 Dockerfile；保留 separate/artifacts、真实评分入口及独立 Verifier。best_method 不放模型，但实际 /workspace/solution artifacts 必须有评分所需模型/配置。

`run_summary.fast_iteration_exception` 默认 used=false，non_training/short_iterations为null。仅启动前冻结7h且全部闭环/干净重跑条件已满足时，used/non_training/short_iterations/rollable_proved才填写true；evidence写依据及duration_evidence.json引用。组包会核摘要与启动前政策相符，为例外任务收集必要的包内证据，并追加与证据一致的中文专家说明；八字段轨迹和run_summary的正式字段不增加。image仍仅指Agent镜像，Verifier及实跑材料写专家说明。候选移交、权限及可选12h诊断见 [PCA环境说明](environment.md)。

需要支撑结论的包内日志/reward/移交清单可在 PACKAGE.json 加 `support_files:[{"source":{"path":"任务内原始文件","sha256":"真实哈希"},"destination":"runtime/文件名"}]`，目标相对包内 expert_evidence。已有 NOP 原件也可定点收录，例如 `destination:"nop_trial/<trial-id>/config.json"`；指定旧题的历史缺证按官方结果处理，新题正常留证。路径须规范、不重复，不得覆盖必交文件；其余制作材料不要求全量提交。

完成后按 [状态登记](state.md) 关闭对应步骤；程序检查不认证 Baseline 代表性、优化收益或平台 Hidden 结果。

## 当前 QA 报告合同

当前源码的 `qa-bind` 复用[当前 QA/打包合同](../packaging.md)：QA 0.3.10 执行副本、schema 6 / innerfield-deployment-v6，QA15 必查。可绑定失败报告安排返修；收口须完成独立语义审阅，无fail/manual，仅通知范围内的warn不单独阻断。旧报告保留身份，由原冻结版本处理，不能转换为当前PASS。独立会话只读最终包，报告保存在包外。

PCA 的完整作者包比 Agent 可见面更宽，待交 workspace 中提供 `qa_exposure_manifest.json`，参考 [模板](../../templates/qa-exposure.example.json)。路径相对 workspace；运行时可写路径用绝对路径。双镜像摘要、UID 和实际视图文件据真实环境填写，工具不会从源码猜造镜像视图。声明和引用检查不等于物理隔离认证。
