# W4：轨迹证据、唯一最佳方法和最终包

状态：合同级实现；尚未对真实题目、实际 Docker/Agent 环境或项目方 QA 做联调。此文档不替代当期专家教程及质检 Skill。

## 边界

- 两条正式 Codex 轨迹的 Agent **在迭代过程中自行写**各自 `formal/output/trajectory.jsonl`。W4 只核验、必要时有据修订，再生成最终 `trajectory_codex.json`、`trajectory_seed.json`。W3 原始日志用于逐轮交叉审阅，不用来凭空生成缺失摘要。
- 默认两条轨迹各须有不少于10小时的可核净有效时长；启动前冻结的非训练7h例外另按 [OP03_DURATION.md](OP03_DURATION.md) 核全部条件。中断恢复和排除异常时间沿用 W3 台账。W4 不把程序判断冒充专家对方法内容、合规性或研究价值的裁定。
- 仅正式唯一 `best_method/` 做 W2 同协议完整 seed 复验及干净快照重跑。Baseline/Reference 的正式多 seed 原始证据由题目方提供到 `optimization_evidence/`，W4 不重新训练。
- 组包器生成 `workspace/`、`expert_evidence/`、`optimization_evidence/` 三个顶层目录。检查器允许有用额外材料，给出格式观察，由独立 QA 按内容分类；不因多交自动失败。制作期原始日志、版本快照、修订审计及 QA 绑定记录留在 `.autoresearch-flow/delivery/`，不混入提交包。缺少包内必交证据不得用包外草稿补救。
- 独立质检由用户在**新会话**对指定最终包运行；本工具只生成准确交接路径、绑定报告与包版本，不调用质检 Skill，也不声称平台审核通过。

## 顺序与命令

统一入口：`python3 AutoResearch新流程/cli.py --format json delivery ...`。以下命令均需显式指定任务根；`delivery check` 例外，只取证最终包。

1. `trajectory-finalize --task-root TASK --track codex|seed [--file CORRECTIONS.json]`：读取 Agent 自写 JSONL，每行恰好为 PCA 八字段，轮次从 1 连续。score 为真实 Public/Dev 原始指标，不是归一化分数。允许用 `--file` 提供有原行哈希、理由和证据的逐行修订；原件和最终版保留。缺失事实不可从日志猜写。
2. `trajectory-review --task-root TASK --track codex|seed --file REVIEW.json`：专家按每轮摘要核对可定位的真实操作/评分记录，填 `consistent: true` 才能进入组包。工具只验记录、引用与哈希，`consistent` 的事实判断由专家承担。
3. `best-select --task-root TASK --file SELECTION.json`：比较两组有效 Public/Dev 评分，快照唯一最终源码。若两组都没有正向合法方法，未修改 Starter 仅在当期权威原文与已有明确授权允许时采用，并解释来源和未提升原因；不得默认为最佳 Agent 方法。
4. `best-verify --task-root TASK --file VERIFICATION.json`：该源码哈希须与 W2 `best_method` 正式 seed 复验完全一致，并提交干净任务快照重跑结果、日志、命令、起止时间、退出码与专家结论。
5. `build --task-root TASK --file PACKAGE.json`：复制明确来源、生成不可混入制作日志的版本目录；先做结构/字段/引用及 B/R/U 线性归一化检查，再绑定 B/R 正式逐次原始 result 哈希与同协议均值、两组有效时长及唯一方法复验。输出 `package_path` 与 `package_sha256`。
6. `check --package-root PACKAGE`：**只读取提交包内部**的格式和必要文件；结果 `format_checked_not_qa` 不代表正式 QA。
7. `archive --task-root TASK --package-root PACKAGE [--max-part-bytes N]`：按排序文件、固定 ZIP 时间戳和 UTF-8 文件名生成可复现 ZIP；默认超过 300 MiB 分卷。分卷按编号拼接即为原 ZIP；校验每卷及整包 SHA-256。ZIP 放在交付包外。
8. `qa-handoff --task-root TASK --package-root PACKAGE`：生成独立新会话使用的准确路径与目录哈希。用户手动运行只读质检。
9. `qa-bind --task-root TASK --package-root PACKAGE --report REPORT.json`：只接受报告 `source.path` 与本包相同的机器可读报告，并检查包哈希未变化；保存状态 `attached_unreviewed`。当前会话再审阅报告和返修，新包必须重新质检。

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
{"protocol_id":"<W2 正式协议 ID>","clean_result":{"path":"<成功重跑 result.json>","sha256":"<SHA-256>"},"clean_log":{"path":"<重跑日志>","sha256":"<SHA-256>"},"reviewer":"<专家>","rationale":"干净快照重跑、方法哈希和结果一致"}
```

重跑结果须含 `status=succeeded`、`method_sha256`、有限 `score`，以及 `execution:{command,started_at,finished_at,exit_code:0}`。

`PACKAGE.json`：

```json
{"protocol_id":"<W2 正式协议 ID>","workspace_directory":"<任务内待交 workspace 相对目录>","optimization_directory":"<任务内待交 optimization_evidence 相对目录>","expert_document":{"path":"<专家作业说明文档>","sha256":"<SHA-256>"},"expert_annotation":{"path":"<expert_annotation.json>","sha256":"<SHA-256>"},"run_summary":{"path":"<run_summary.json>","sha256":"<SHA-256>"}}
```

所有引用使用**任务根内相对路径和 SHA-256**；训练型任务的模型、日志、checkpoint 应在 `optimization_directory` 下按教程保留。构建时从 W2 读取 `evaluation_protocol` 并补入包内 comparison_summary；非训练任务不强制模型，确定性非训练任务可按已冻结协议单次评估，随机/训练型及高方差重复数保持 W2 要求。专家说明、标注 JSON 与摘要须按当期教程填写；工具只核可机械判断的字段及与 W2/W3 台账的基本一致性。

## 验收边界

PCA 包要求两个 Dockerfile、独立 context、非空 starter、separate/artifacts 和真实 test.sh；不强制等价 grader 的内部文件名。best_method 不放模型，但实际 /workspace/solution artifacts 必须有评分所需模型/配置。

`run_summary.fast_iteration_exception` 默认 used=false，non_training/short_iterations为null。仅启动前冻结7h且全部闭环/干净重跑条件已满足时，used/non_training/short_iterations/rollable_proved才填写true；evidence写依据及duration_evidence.json引用。组包会核摘要与启动前政策相符，为例外任务收集必要的包内证据，并追加与证据一致的中文专家说明；八字段轨迹和run_summary的正式字段不增加。image仍仅指Agent镜像，Verifier及实跑材料写专家说明。候选移交、权限及可选12h诊断见 [PCA环境说明](PCA_ENVIRONMENT.md)。

需要支撑结论的包内日志/reward/移交清单可在 PACKAGE.json 加 `support_files:[{"source":{"path":"任务内原始文件","sha256":"真实哈希"},"destination":"runtime/文件名"}]`，目标相对包内 expert_evidence。路径须规范、不重复，不得覆盖必交文件。只纳入必要证据；该可选接口不要求每题提交全部制作文件。

合成测试覆盖轨迹缺失/修订原件保存、逐轮审阅、唯一方法哈希复验、包边界、确定性归档及旧 QA 报告失效；它们不证明真实题目的优化面合格、Baseline 代表性、Reference 改进、GPU 镜像兼容或平台 Hidden 结果。真实题目和通用工具的最小联调仍属于 W5；日常阶段登记和冻结已接入 [STAGE_STATE.md](STAGE_STATE.md)。

## 当前 QA 报告合同

独立会话使用 v0.3.1；只读最终包，报告保存在包外。`qa-bind` 接受 schema_version=4、policy.name=implementation、policy.revision=research-quality-v3 且 QA/G/H 全部唯一的报告，失败报告可绑定供返修。6.4/6.5 收口另要求独立报告 PASS、review.completed=true，禁止借 exception/platform_only 手动关闭 fail/manual；QA15 固定 not_applicable，QA04/19、H05/06 按 Skill 的适用条件处理。

PCA 的完整作者包比 Agent 可见面更宽，待交 workspace 中提供 `qa_exposure_manifest.json`，参考 [模板](templates/qa-exposure.example.json)。路径相对 workspace；运行时可写路径用绝对路径。双镜像摘要、UID 和实际视图文件据真实环境填写，工具不会从源码猜造镜像视图。声明和引用检查不等于物理隔离认证。
