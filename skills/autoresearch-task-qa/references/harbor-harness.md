# Harbor Harness 兼容性检查

本规范落实用户新增的 Harness 要求，作为 QA17 的六个子项，同时关联 QA06、QA18、QA21。默认只读取提交的代码与已有 Trial 证据，不执行待检代码；文件齐全不等于已验证运行。

## 依据与版本

- 内部：[Harbor Framework 调研分析](https://bytedance.larkoffice.com/wiki/A7FUwJBALici6Gku3rWc4EsinLf)，读取修订 3790。重点采用 Task/Job/Trial 分层、配置覆盖、测试/结果约定；文档中的研究建议、未来平台目标和示例不是全部强制交付项。
- 官方：核对 [Environment](https://docs.harborframework.com/core-concepts/tasks/environment)、[Verifier](https://docs.harborframework.com/core-concepts/tasks/verifier)、[Configuration](https://docs.harborframework.com/core-concepts/tasks/configuration)、[Separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier) 与 [Solution](https://docs.harborframework.com/core-concepts/tasks/solution)；旧 Task Structure 链接会重定向，优先使用这些直接页面。
- 配置与结果的精确类型以目标版本的官方 `src/harbor/models/task/config.py`、`models/trial/config.py`、`models/job/config.py`、`models/trial/result.py`、`models/verifier/result.py` 及目标 provider 实现为准，可从 [官方仓库](https://github.com/harbor-framework/harbor) 读取。不要假定 main 永远等于已部署版本。

先读[当前内场部署口径](innerfield-deployment.md)：默认 innerfield-maso-v1，原生Harbor支持不等于内场支持。每sandbox必须单容器，任务不得部署或调用额外工作环境；不用当前MASO不支持的Compose；保留separate与独立sandbox。先查包内版本锁定、运行配置或平台说明。未声明版本不直接判失败，可以明确采用 `official-docs@2026-09-18` 作为静态对照版本，并在 version_basis 写规范 URL 和“文档静态核对，未做原生 schema 加载”；只有实际读过源码才注明源码。provider 可从明确 Docker 配置等材料推定，注明推定依据；不能确认则 unknown 和未完成。不能把文档快照说成已安装版本。

不要求最新 schema_version 必填；按目标版本默认值、别名与实际类型判断。一般Harbor的memory/storage、memory_mb/storage_mb等字段须核对目标版本；但当前内场明确不支持storage_mb、no-network/网络白名单，不能因原生字段合法判通过。warning或降级联网不是约束生效。原生不识别的自定义元数据本身不一定报错，但不能把 [resources] 或 [entrypoint] 当成原生生效的资源限制或入口配置，除非有实际适配映射。

启动environment的基础网络策略与Agent/Verifier执行阶段请求分别核对；执行阶段public不抵消启动时no-network/allowlist仍不受内场支持的事实。默认 implementation 交付禁止 Compose（generic-harbor 也不豁免此文件交付规则）：在选定 task 根的 `environment/`（Agent）与 `tests/`（Verifier）直属位置发现 `docker-compose.yaml`、`docker-compose.yml`、`compose.yaml` 或 `compose.yml` 即 fail；与 Dockerfile 并存、预构建镜像、显式 docker_image 或 compose_review.selection=unused 均不豁免。自动扫描只覆盖这两个正式运行目录的直属文件，不递归扫描 docs、examples、history 或其他资料目录；非标准运行入口仍须人工核对，不得据未命中声称没有 Compose。详见[内场部署口径](innerfield-deployment.md)。

## 教学示例与严格路径

先读 [Docker路径契约](docker-path-contract.md)。当前默认 environment/ 为 Agent 构建上下文，专用 Verifier 构建用 tests/；复用 Solver 镜像则按目标版本运行时上传 tests。以下为历史附件说明：2026-09-18实际example.zip要求task-root构建上下文与/workspace容器根；这不等于已确认原生Harbor接受其自定义task.toml。采用teaching-task-root-v1或harbor-environment-v1时记录来源，不能混用。harbor.path_contract的确定路径失败自动使H03失败；动态语法未解析须补语义复核。示例tests/test.sh仅pytest，正式验收入口还必须实际评分并写reward，不能将合同测试成功当任务评分。

## 独立 Verifier 与公开/私有评测

本项目要求 `task.toml` 显式包含 `[verifier] environment_mode = "separate"`，Solver/Verifier 为不同 sandbox，可复用 Solver 镜像，或选择专用 Verifier 镜像/构建。复用环境配置时 tests 上传至 /tests；显式 Verifier 镜像或 tests 构建定义优先，须预置入口及私有材料。按目标版本核对，不一律要求 tests/Dockerfile。Agent 使用公开 Dev 反复验证方法；结束前恢复 Dev 最佳候选和必要模型/配置，平台再移交最终提交给独立 Verifier 正式评分。Verifier 执行评分及候选程序，无需启动另一个 Coding Agent。本版不假设存在每轮 Hidden 调用服务。

公开 Dev 评分代码及公开数据必须供 Agent 使用。若原来位于 tests/，先拆出公开部分，通常放入 environment/public_eval/，也可等价布局；不能笼统禁止 Agent 包含“评分实现”。最终私有测试数据、标签、参考答案或私有评估逻辑才是隔离对象。核对 COPY、忽略规则、镜像层和运行时挂载，不能以目录名称判断最终可见性。

Hidden 评测材料对训练与非训练任务均需要；可以是预置文件、可复现生成逻辑或安全注入的材料。目录不必叫 tests/hidden_assets/，不要求为了过检造一个空目录或占位文件。`review.harbor.hidden_review` 记录实际准备方式、材料和评分调用依据，见 implementation-report.md；只写“运行时注入”而无实现/平台依据不能通过。

专用 Verifier 可从 tests/ 上下文构建，镜像自行提供 `/tests/test.sh`、评分实现及必需依赖，该分支不由 Harbor 运行时上传 tests/。复用 Solver 环境则创建新 sandbox 并上传 tests/；评分依赖须已在复用镜像准备，不能依赖 Agent 临时安装包、缓存或未移交文件。正式评分只读取题面及协议允许的提交物。

核对 `test.sh` 的真实读路径与 task.toml 顶层 artifacts 源路径。除默认 `/logs/artifacts/` 外，其他所需输出须明确移交；Verifier 保持源绝对路径，artifacts 的 destination 仅是宿主机收集位置，不能当作容器内重映射。教程运行时提交面是 `/workspace/solution`，其他任务可在 `submission_paths` 据实声明。源码 `solution/solve.sh` 为可选 Oracle，与运行时提交面不同。静态路径通过不表示已完成构建、物理隔离或动态传输。

## 六项复核

| ID | 阅读与判断 |
|---|---|
| H01 任务目录与 Hidden | 选定真实 task 根；核对 instruction.md、task.toml、实际选中的镜像/构建、测试上传或预置入口及依赖。通过 hidden_review 核对私有材料/生成/注入与评分器调用，接受等价目录。不一律要求 tests/Dockerfile。Oracle 可选，多步/Windows 按目标版本检查。 |
| H02 版本与配置 | 读完整 TOML，检查语法、字段类型、配置位置、目标版本、部署profile实际能力以及显式 separate。不能把 TOML 可解析等同原生 schema 验证。Python 3.11+ 的 tomllib 可用于语法检查；其他环境用可信解析器或保留未完成。自定义字段须有真实适配。 |
| H03 环境、路径与提交物 | 按部署profile与目标版本镜像优先级核对实际COPY/镜像内容、WORKDIR、入口、依赖与可见边界；内场预构建可用镜像，每sandbox必须单容器，不用Compose；按 innerfield-deployment.md 沿启动和评分调用链核对执行位置，拒绝题包要求／允许或实际依赖额外工作环境；题包符合规则但Agent自行违规时按QA18审查并区分责任。平台创建Agent/Verifier、运行前构建镜像、本地进程及正常模型/数据服务请求须区别处理，不能仅凭关键词判失败；无法确认的关键调用记manual。复用环境上传 tests，专用镜像/构建预置 tests，不能根据镜像相同猜测上传。沿评分调用确认必要提交物与 artifacts。历史 task-root profile 需适配依据；私有 tests 不得进入 Solver。确定路径错误 fail，动态语法待核实；已有 sandbox 身份和上传证据需交叉核对，不认证完整物理隔离或12h稳定性。 |
| H04 测试入口与 reward | 沿 test.sh 实际调用链检查必填参数、标量主分数及失败处理；须写 /logs/verifier/reward.txt 的有限数值，或 reward.json 非空有限数值对象。两者并存按优先 reward.json 核对。自定义 result.json、stdout score、注释或死代码不算接口完成。合法负数或 >1 与业务归一化门槛分开判断。 |
| H05 Job/Trial 调用配置 | 有配置时核对所选 task/provider/agent、有效覆盖、启动条件、verifier 未被禁用；检查重复键、错误路径、空选择和明确冲突。单任务 CLI 可用，不强制 job.yaml；确无配置可 not_applicable，已有反证不能跳过。 |
| H06 NOP 自检记录 | 新题必要 NOP 缺证失败、版本待核仍待核；指定旧题按[官方路径](../../../docs/legacy-qa.md)处理。无记录记 not_run，其余未核验记 unverified。已有记录核同次config/result/reward/日志、版本、separate及分数一致性，真实执行异常仍fail。可复用平台记录，0分本身不失败。 |

H01–H04 与 H06 必查；H05 按已有材料适用。NOP缺证使H06及派生QA17为warn，其他H项失败或待核不被覆盖。报告同时列静态结论与实际运行状态。

## 已有 NOP 自检记录

NOP 是 no-operation Agent：不调用模型求解，也不修改初始工作区；已有 Starter 会保留，所以不能把 NOP 一律称为“空提交”。它让 Harness 走完启动、Agent 结束、提交物移交和独立 Verifier 的实际执行分支，帮助发现构建、入口、缺依赖、路径及 reward 收集问题。若无提交触发早退，它只覆盖那条分支，不能证明完整 Hidden 评估或有效候选可运行。

专家或平台使用当前题包版本及独立 sandbox 配置，在目标 Harbor 环境选择 `nop` 跑一次。构建成功、Trial 正常结束、独立 Verifier 已执行并产出有效 reward 即满足本项的运行要求。将同一 Trial 的配置、结果、reward 和日志放入 expert_evidence/，版本与自检结果可在已有配置、日志或专家说明中交代。平台已有同版本记录可以复用。本只读 Skill 核对记录，不自动发起运行。

检查的是是否符合题目约定的处理行为，而非 NOP 得分高低。0 分可能是预期，也可能来自错误早退，必须结合异常、退出状态与评分日志判断。完成了 NOP 仍不能替代公开 Dev 的实际反馈、有效提交的正式评分、模型独立重载与 Baseline/Reference 改善证据。

## 自动证据校验与报告

H06 自动校验已有完整单步Trial：config/result Agent身份一致且为nop、separate、有结束时间且无异常、result奖励与reward文件一致、配置/日志非空且同目录。版本可用已有配置/日志/专家说明的trial_task_binding，不强制新增哈希。新题缺证及版本待核正常处理；指定旧题通过官方独立结果判断；已交原件的真实异常仍阻断。自动检查不鉴定日志真伪，不伪造单步材料；run_summary 哈希另归 QA21 检查。

Harbor 的 agent/trajectory.json 若为 ATIF，按其声明版本识别；专家 AutoResearch 轨迹仍采用八字段，不互套 schema。artifacts 配置存在不等于文件已成功移交；已有运行记录应检查实际移交结果。源码参考解、私有轨迹不应成为 Agent 前置上下文。

报告保留21行，QA17 汇总 H01–H06；细项与路径证据写入 report.json.harbor。已有记录一致称“已有 NOP 自检记录支持当前版本构建与运行可用，非独立复跑”；无材料显示 not_run 和实际失败／待核；指定旧题另附官方豁免结果，不称执行通过。

只有用户另行要求动态验证时，才依据目标 Harbor CLI help、provider、隔离环境和授权范围制定命令。在授权的可丢弃环境运行并保留配置、任务版本、日志、reward 与 Trial 结果；不在宿主机直接执行未知 test.sh/solve.sh 或导入候选模块。未实际运行不得声称动态验证完成。

一般Harbor的镜像选择按目标版本核对：verifier.environment.docker_image → tests/Dockerfile（原生也可支持Compose）→ environment.docker_image → environment/Dockerfile（原生也可支持Compose）。当前内场不支持Compose，应按平台要求预构建镜像并填写docker_image；不得把原生选择分支写成内场可用性证明。前两种不自动上传 tests；后两种在新 Verifier sandbox 上传 tests。镜像 digest 相同不改变这一规则。配置 separate 不独立证明实际物理边界；已有 sandbox 身份/上传记录应检查，相同身份属于明确反证。原生官方说明见 [Separate verifier](https://docs.harborframework.com/tasks/separate-verifier)。2026-10-12 已核对当前官方文档及 main 的 verifier_mode.py、trial.py 与 verifier.py；这不代表已核验目标部署版本，实际版本与 provider 仍按提交材料复核。
