# PCA 规则锁与 QA 口径裁定

日期：2026-09-30。正式原文为 PCA-20260929；当前目录中 T:PCA-20260929:L 为该快照行号。W0 文件保留为 v4 历史，不再作为新版教程定位。

教程优先于旧 QA；保留 G/B/QA/H 全部 38 项逆向映射及原有 49 条稳定规则 ID；v0.3.1 新增 AR-050。QA15 仍跳过。不得将旧 QA 的静态通过或历史例外外推为免做新版真实链路。

## 冲突裁定

| 旧要求 | 本版裁定 | 依据 |
|---|---|---|
| task-root COPY / 单镜像 | environment 与 tests 独立 context | L38–64 |
| Agent 可读 tests | 最终 tests 不可见，公开 grader 拆出 | L144–165 |
| 每轮两字段 | 八字段，score 为原始 Public/Dev 指标 | L620–646、829–874 |
| 容器 10h | 容器 12h；双轨净有效仍各 10h | L70–72 |
| Hidden 一律为空 | 私有预置/生成/安全注入按授权选用 | L455–464 |
| 无 Harness 记录可以不适用 | 新版必须真实 Harbor 自验，正式 Hidden 无权限可用授权替代数据 | L529–541 |
| 题面无需 replicate | 声明 seed/replicate 规则 | L948 |

## 本次语义修订

### AR-003

旧版：第一阶段只定 B/R 候选与选择原则；正式锚点经真实验证后才冻结。Baseline 为合理可运行 Starter 的正式聚合结果，不能另设更弱 B；scaffold 特例须依权威或明示例外裁定。

新版：第一阶段只定 B/R 候选；验证后才冻结。可运行 Starter 默认作 Baseline；Starter 为 Scaffold 时须另有合理可执行朴素 Baseline，并将 B 绑定其正式聚合结果，不能另设更弱零点。

### AR-004

旧版：`workspace/harbor_task` 为 Agent 任务面，`workspace/reference`、`expert_evidence`、`optimization_evidence` 不可见；`solution/` 为题面声明的唯一候选写入面。

新版：完整 harbor_task 不整体暴露给 Agent。Agent 只见公开题面、依赖、Starter、Public/Dev 及入口；/workspace/starter 只读，/workspace/solution 为候选写入面。私有 tests、Reference、已汇总专家证据不可见；仅本轨新产物输出目录可写。

### AR-005

旧版：`task.toml` 须能解析；任务、资源、指标方向、字段类型/原生位置和入口与题面及真实执行一致；示例资源数值不能当通用常量，自定义字段须有目标 Harbor 版本的适配映射。

新版：task.toml 按目标 Harbor 版本验证：顶层 artifacts 仅 /workspace/solution，verifier.environment_mode=separate，Agent/Verifier 分别声明实际资源与依赖。示例 schema_version=1.3 不是跨版本常量。

### AR-006

旧版：`instruction.md` 具有八个有实质内容的章节/语义等价部分，写清问题、指标、可改范围、边界、真实提交物、迭代和完成条件；随机性任务题面说明 seed 与有效提升阈值，不额外强制题面写 replicate 次数。

新版：英文题面八章节或语义等价结构完整，写明问题、指标、合法方法空间、边界、真实提交物、迭代和完成条件；随机任务声明 seed/replicate 规则与有效提升要求，不照抄不存在的接口。

### AR-009

旧版：Docker 构建 context、COPY、WORKDIR、任务根、入口和 provider/profile 必须贯通；确定的越界/缺源路径不通过。静态通过不等于构建成功。

新版：Agent context=environment/，Verifier context=tests/，分别 Dockerfile，禁止 COPY ../ 和旧 task-root 混用。正式入口 bash /tests/test.sh 不依赖 cwd。必须实际构建并验证目标 Harbor 双镜像移交出分；静态解析不等于实跑。

### AR-010

旧版：环境能在声明资源/时限内运行 Starter、Reference 与评分；排查 OOM/FD/磁盘/日志堆积，容器按教程正文可稳定存活至少 10 小时。本地验证与平台稳定性结论分开。

新版：环境可在声明资源运行 B/R/评分，容器稳定存活至少 12h；与双轨各 10h 净有效时长分别核算。实际证据可复用，不以时长相加、静态检查冒充稳定性验证。

### AR-011

旧版：Agent 不得看见 Hidden 内容、Reference、专家证据、密钥；固定训练/评分面不可被篡改或须可信恢复；发现泄漏/伪造路径按隔离失败返修，不仅扣分。

新版：Agent 不可见私有 tests/Hidden/Reference/已汇总专家证据/凭据；公开固定面不可篡改。Verifier 内候选仍不可信，须限制文件、用户和进程权限，不在全私有权限 grader 内直接 import 候选；隔离失败返修而非仅扣分。

### AR-014

旧版：Public/Dev 入口应在 Agent 合法环境可调用；正式 Hidden 由平台注入、运行与审核，不能把空 `hidden_assets/` 当已有 Hidden。

新版：Agent 每轮合法调用公开评分，结束后 Harbor 移交候选并启动独立 Verifier。Hidden 可按授权私有预置、私有规则生成或安全注入；无正式 Hidden 权限用授权同接口数据实跑并标平台待验，不能冒称正式 Hidden 通过。

### AR-017

旧版：Baseline 的输入、标签、损失、更新、推理及 checkpoint 正常；实际训练量、曲线和停止原因可核验，不把计划 epochs 冒充已完成。

新版：核 Baseline 输入、标签、损失、更新、推理和模型正常，以实际 steps/tokens/样本量、曲线与停止原因查训练充分性；统一预算未完全收敛不自动失败。已批准 debug 题按声明核健康对照。

### AR-020

旧版：正式 seed 集真实、完整、逐一成对；随机训练从初始化独立进行，不能复制完成训练 checkpoint 冒充独立轮。

新版：正式 seed 集真实、完整且 B/R 逐一成对；随机训练各 seed 独立执行。可使用事前声明的合法共享预训练起点，不能复制本题完成训练 checkpoint 冒充独立重复。

### AR-033

旧版：Harbor 任务根、instruction/task.toml、环境和测试入口与引用文件齐全；多层外包或分卷不能误作独立完整任务。

新版：完整任务包含 instruction.md、task.toml、environment/Dockerfile、environment/starter/、tests/Dockerfile 和 tests/test.sh；公开/私有 grader 内部组织允许等价实现。仓库根 solution 不再是 Agent 镜像构建输入。

### AR-034

旧版：正式测试入口能沿实际调用链写 Harness 接收的有限 reward，不能只 stdout 或自定义 result；reward.json 优先级/旧文件遮蔽要处理。

新版：Verifier 的 /tests/test.sh 必须实际执行可信评分并写 /logs/verifier/reward.txt 或数值对象 reward.json；仅 pytest 成功不算出分，清理旧结果避免遮蔽，不采信候选自报。

### AR-035

旧版：若有 Job/Trial 配置，任务/provider/agent/覆盖/入口一致且 verifier 未禁用；没有且不声称已有运行可不适用。

新版：Job/Trial 的任务/provider/agent/入口一致、verifier 未禁用；实际验证 separate 和 artifacts 生效，两镜像预构建。不新增每轮 Hidden 服务，不以 verifier.environment 小节存在替代实跑。

### AR-036

旧版：已有 Harness 运行材料须核同一 Trial 的配置、结果、reward、日志和任务版本；没有运行材料只可称静态接口检查，不能称平台复现。

新版：必须具备目标 Harbor 实际端到端材料：版本、同一 trial 配置、移交、独立环境、reward 与日志。无正式 Hidden 权限可用授权自验数据；仅 Docker 组件或静态检查不能称 Harbor 已通过。

### AR-037

旧版：两条固定模型组合独立使用同一任务/Prompt/公开协议与资源配置，独立空输出目录，不共享 Reference/Hidden/对方轨迹。

新版：固定 Codex+GPT-5.6 Sol 与 Codex+Seed 2.1 Turbo，同任务/Prompt/公开协议，独立输出。推理档位默认各 provider 实际支持的最高有效档位，不能只把字符串写为 max 或静默降档。

### AR-040

旧版：两条最终轨迹分别为 `trajectory_seed.json`、`trajectory_codex.json`，顶层 `rounds`，每轮仅递增 `round` 与 1–3 句 `method_summary`；运行期 JSONL 需转换，不把 ATIF 套入本格式。

新版：Agent 逐轮自写八字段 round/policy_name/method_summary/status/score/failure_reason/retained_best/time，最终两份 JSON 顶层 rounds。score 是 Public/Dev 原始指标，失败未出分为 null；成功 ok 且原因 null；完成时间 YYYY-MM-DD HH:mm:ss，不替代有效时长。不另加日志字段。

### AR-041

旧版：只交唯一 `best_method/` 的完整可运行代码/配置，按合法 Public/Dev 分数选出并在干净任务快照替换 solution 成功复验；不交历史代码或 checkpoint。无提升 Starter 方案仍需 D22 条件核对。

新版：只交唯一 best_method 完整代码/配置，不含模型或历史版本；依协议复验。每轨结束前复测当前最佳并将代码及必需模型/配置恢复至 /workspace/solution，artifacts 只传此候选。必要模型不得遗留未移交缓存。

### AR-042

旧版：最终包有三类顶层职责；`expert_evidence` 包含中文专家说明、最终方法、expert_annotation、run_summary、两条轨迹；探索额外文件只在支撑关键主张时保留。

新版：三类最终目录职责不变，专家证据含说明、唯一方法、标注 JSON、摘要和两条轨迹。最小充分交付，不把全部探索材料或内部流程账本机械列为必交。

### AR-043

旧版：`expert_annotation.json` 只载题目语义、指标方向、同协议 B/R/U 与隔离声明，不混入运行日志或审核结论。

新版：expert_annotation 载题目、指标与同协议锚点及隔离声明；中文专家说明补双镜像 context/命令/不可变标识、目标 Harbor 版本/实跑、候选权限和 Hidden 授权方式，不自称平台通过。

### AR-044

旧版：`run_summary.json` 如实写双轨实际有效时长/轮数、自验状态及证据目录齐备，不把预算、容器 uptime 或平台审核写成实际完成。

新版：run_summary 如实写两轨净有效时长与实际轮数；image 仍仅 Agent 镜像。例外资格键 non_training/short_iterations 不使用时为 null；当前流程坚持各 10h，不自动启用 7h。Verifier 信息放专家说明。

### AR-048

旧版：核心依赖与镜像应可在声明 Harbor/云资源上构建，不靠内部挂载、内部账号或未声明服务；依赖版本可追溯，清理临时文件并控制体积。平台原生 profile 若确有合法挂载/预构建镜像，按目标版本和适配证据核对，不能机械禁止。

新版：两套镜像各自依赖自足；最终评分不依赖 Agent 临时安装、缓存或未移交文件。依赖可追溯、体积受控，真实目标 Harbor/profile 可用，不照搬题目样例资源。

### AR-049

旧版：Train/Public/Dev 数据版本和切分留指纹；许可或隐私受限资产、正式 Hidden 与原始解法来源黑名单走平台安全入口，不向 Agent 或提交包错误复制。

新版：Train/Public/Dev 指纹与切分固定；公开及正式指标/约束对齐但分别绑定 split 与 B/U 标定，不把 Dev 值称 Hidden。私有资产按授权交付给 Verifier/平台，不能错误复制给 Agent。

## 全规则定位与阶段

| ID | 阶段 | 当前规则 | 来源 |
|---|---|---|---|
| AR-001 | 1 | 领取后核任务材料、出题模式、数据许可、指标方向、资源与可见性；变体必须独立且有实质方法差异。 | T:PCA-20260929:L80–116 |
| AR-002 | 1,2,3 | 优化面须能程序评分、支持非纯参数的方法改动，接口及 guard 真正允许执行；不能只让 Agent 在固定方法中找数字。 | T:PCA-20260929:L18–22,251–282; Q:research-quality.md#G01 |
| AR-003 | 1,2,3 | 第一阶段只定 B/R 候选；验证后才冻结。可运行 Starter 默认作 Baseline；Starter 为 Scaffold 时须另有合理可执行朴素 Baseline，并将 B 绑定其正式聚合结果，不能另设更弱零点。 | T:PCA-20260929:L20,160,350–449; Q:research-quality.md#G02 |
| AR-004 | 1,2,3,4,5,6 | 完整 harbor_task 不整体暴露给 Agent。Agent 只见公开题面、依赖、Starter、Public/Dev 及入口；/workspace/starter 只读，/workspace/solution 为候选写入面。私有 tests、Reference、已汇总专家证据不可见；仅本轨新产物输出目录可写。 | T:PCA-20260929:L38–64,144–165,618; Q:submission-format.md#1 |
| AR-005 | 2,3,4,5,6 | task.toml 按目标 Harbor 版本验证：顶层 artifacts 仅 /workspace/solution，verifier.environment_mode=separate，Agent/Verifier 分别声明实际资源与依赖。示例 schema_version=1.3 不是跨版本常量。 | T:PCA-20260929:L171–217; Q:harbor-harness.md#H02 |
| AR-006 | 2,3,4,5,6 | 英文题面八章节或语义等价结构完整，写明问题、指标、合法方法空间、边界、真实提交物、迭代和完成条件；随机任务声明 seed/replicate 规则与有效提升要求，不照抄不存在的接口。 | T:PCA-20260929:L219–282,948; Q:implementation-policy.md#QA01/QA11/QA19/QA20 |
| AR-007 | 2,3,4,5,6 | Agent 题面不得直接泄露论文/官方解法来源、Hidden 答案或 Reference 细节；公开背景与必要接口不是泄露。 | T:PCA-20260929:L280,515–525; Q:implementation-policy.md#QA01/QA07/QA08 |
| AR-008 | 2,3,4,5,6 | 题面核心硬约束须有可识别的环境或 verifier 执行逻辑；正常读写、网络、资源、并发政策要与执行边界一致，不能只写禁令。 | T:PCA-20260929:L251–282,509–525; Q:implementation-policy.md#QA05/QA20 |
| AR-009 | 2,3,4,5,6 | Agent context=environment/，Verifier context=tests/，分别 Dockerfile，禁止 COPY ../ 和旧 task-root 混用。正式入口 bash /tests/test.sh 不依赖 cwd。必须实际构建并验证目标 Harbor 双镜像移交出分；静态解析不等于实跑。 | T:PCA-20260929:L38–64,288–324,529–541; Q:docker-path-contract.md#两种受支持 profile; Q:harbor-harness.md#H03 |
| AR-010 | 2,3,4,5,6 | 环境可在声明资源运行 B/R/评分，容器稳定存活至少 12h；与双轨各 10h 净有效时长分别核算。实际证据可复用，不以时长相加、静态检查冒充稳定性验证。 | T:PCA-20260929:L70–72,324 |
| AR-011 | 2,3,4,5,6 | Agent 不可见私有 tests/Hidden/Reference/已汇总专家证据/凭据；公开固定面不可篡改。Verifier 内候选仍不可信，须限制文件、用户和进程权限，不在全私有权限 grader 内直接 import 候选；隔离失败返修而非仅扣分。 | T:PCA-20260929:L144–165,464,515–525; Q:implementation-policy.md#QA10 |
| AR-012 | 2,3,4,5,6 | 评分前清理 Agent 可能预写的结果，最终结果由可信评分侧计算并原子写入；不采信候选自报分数。 | T:PCA-20260929:L455–464,515–525; Q:implementation-policy.md#QA06/QA09 |
| AR-013 | 2,3,4,5,6 | 提交的 Git 历史不得留答案线索；有 `.git` 时检查 remotes、tags、reflog 和相关修复提交清理。 | T:PCA-20260929:L523; Q:implementation-policy.md#QA12 |
| AR-014 | 2,3,4,5,6 | Agent 每轮合法调用公开评分，结束后 Harbor 移交候选并启动独立 Verifier。Hidden 可按授权私有预置、私有规则生成或安全注入；无正式 Hidden 权限用授权同接口数据实跑并标平台待验，不能冒称正式 Hidden 通过。 | T:PCA-20260929:L9–13,455–464,529–541 |
| AR-015 | 2,3,4,5 | 首次正式 Baseline 前固定数据/切分/指标/预算/正式 seed/重复/聚合/选择规则；B/R 和最终待评方法用同一协议。实质变更须重验受影响锚点。 | T:PCA-20260929:L350–449,491–503 |
| AR-016 | 2,3 | Baseline 来源、任务适用性、角色和选择理由可辩护；年代、简单或大分差本身不是失败理由，代表性不足须有任务/资源/协议可比证据。 | T:PCA-20260929:L18–34; Q:baseline-quality/SKILL.md#B01/B08 |
| AR-017 | 2,3 | 核 Baseline 输入、标签、损失、更新、推理和模型正常，以实际 steps/tokens/样本量、曲线与停止原因查训练充分性；统一预算未完全收敛不自动失败。已批准 debug 题按声明核健康对照。 | T:PCA-20260929:L24–34,350–449; Q:baseline-quality/SKILL.md#B02 |
| AR-018 | 2,3 | B/R 使用共同数据、评价、预算上限和可比较资源口径；研究变量允许的结构或训练差异不机械判违规，实际成本与提升主张要匹配。 | T:PCA-20260929:L28,350–449; Q:baseline-quality/SKILL.md#B03 |
| AR-019 | 2,3 | 双方参数与搜索机会须披露且符合共同约束；不能只给 B 异常配置或挑最差 B、最好 R。 | T:PCA-20260929:L18–34; Q:baseline-quality/SKILL.md#B04/B08 |
| AR-020 | 2,3 | 正式 seed 集真实、完整且 B/R 逐一成对；随机训练各 seed 独立执行。可使用事前声明的合法共享预训练起点，不能复制本题完成训练 checkpoint 冒充独立重复。 | T:PCA-20260929:L34,350–449; Q:baseline-quality/SKILL.md#B05 |
| AR-021 | 2,3 | 适用 sanity 对照低于/优于 B 时查实现与代表性；没有 sanity 不能自动判失败，不造锚点。 | T:PCA-20260929:L18–34; Q:baseline-quality/SKILL.md#B06 |
| AR-022 | 2,3 | Reference 实际变化只在允许优化面；固定因素一致，额外数据/资源/评测变化要披露；多项方法变化可作联合比较，声称单项贡献才需对应归因证据。 | T:PCA-20260929:L350–449; Q:baseline-quality/SKILL.md#B07 |
| AR-023 | 2,3 | B01–B08 中阶段 2 已可判的适用子条件通过后才冻结 B；B03/B07 跨方法部分标注所需证据与阶段 3 截止，不得预判通过或无限挂起。 | T:PCA-20260929:L18–34; Q:baseline-quality/SKILL.md#八项检查 |
| AR-024 | 2,3,4,5,6 | `optimization_evidence/` 包含 `训练证据说明.md`、双方全部正式逐 seed `result.json`/原始 `run.log`、汇总；失败/较差运行保留，缺真实运行信息写 null 并说明，不造日志。 | T:PCA-20260929:L350–449; Q:submission-format.md#2 |
| AR-025 | 2,3,4,5,6 | 训练型正式每轮留真实模型、哈希与干净进程重载复评分；非训练型不建空模型目录，合法预训练起点须披露。 | T:PCA-20260929:L350–449; Q:submission-format.md#模型产物 |
| AR-026 | 3,4,5,6 | Reference 有合法可执行入口，使用同一正式 seed/协议独立重复并实际改善 B；证明可解但不是唯一答案或分数上限。 | T:PCA-20260929:L338–449; Q:implementation-policy.md#QA03/QA13 |
| AR-027 | 3,4,5,6 | 随机评估若协议未规定，B/R/待评各至少 3 次，波动大至少 5 次；声明了 5 个就全交；三方同次数、seed、聚合，不挑最好一次。 | T:PCA-20260929:L405–449,491–503; Q:research-quality.md#G03 |
| AR-028 | 3,4,5,6 | 随机改善用 B 原始指标样本标准差（n−1）比较：正向 Δ≥3σ_B；达到 3σ_B 但低于 5σ_B 时按教程增加重复次数并标记平台复核，≥5σ_B 为强证据；σ_B=0 仍需真实正改善。 | T:PCA-20260929:L405–449,491–503; Q:research-quality.md#G03 |
| AR-029 | 3,4,5,6 | 确定性改善须真实正向且满足适用归一化门槛；不恢复已删除的统一 5% 规则；题目事前另定阈值则同时核。确定性须有依据，不因固定训练 seed 自动推定。 | T:PCA-20260929:L18–34,491–503; Q:research-quality.md#G03; Q:implementation-policy.md#QA04/QA19 |
| AR-030 | 3,4,5,6 | B=0、预计可达 U=1；无法可靠估 U 才以 Metric Ceiling 代替；评分连续、单调、方向明确、不裁剪，超 U 可大于 1。U 来源独立于事后分数反推。 | T:PCA-20260929:L466–503; Q:implementation-policy.md#QA02 |
| AR-031 | 3,4,5,6 | Reference 在声明 Public/Dev 自验口径归一化分数为 [0.15,0.8]，且仍有合法改进空间；headroom 原则上 ≥3σ_B，低于时说明风险并审查，不升级为绝对失败阈值。 | T:PCA-20260929:L466–503; Q:research-quality.md#G03; Q:implementation-policy.md#QA14 |
| AR-032 | 3,4,5,6 | 成功输出可信标量分数和原始指标；非作弊 Hard Gate 违反为 -1 且不参与排序，格式/超时/资源/基础设施错误分类、给可执行修复信息；隔离失败不按普通扣分处理。 | T:PCA-20260929:L505–513; Q:implementation-policy.md#QA06 |
| AR-033 | 2,3,4,5,6 | 完整任务包含 instruction.md、task.toml、environment/Dockerfile、environment/starter/、tests/Dockerfile 和 tests/test.sh；公开/私有 grader 内部组织允许等价实现。仓库根 solution 不再是 Agent 镜像构建输入。 | T:PCA-20260929:L118–165,455–464; Q:harbor-harness.md#H01 |
| AR-034 | 2,3,4,5,6 | Verifier 的 /tests/test.sh 必须实际执行可信评分并写 /logs/verifier/reward.txt 或数值对象 reward.json；仅 pytest 成功不算出分，清理旧结果避免遮蔽，不采信候选自报。 | T:PCA-20260929:L455–464,515–541; Q:harbor-harness.md#H04; Q:implementation-policy.md#QA06/QA17 |
| AR-035 | 2,3,4,5,6 | Job/Trial 的任务/provider/agent/入口一致、verifier 未禁用；实际验证 separate 和 artifacts 生效，两镜像预构建。不新增每轮 Hidden 服务，不以 verifier.environment 小节存在替代实跑。 | T:PCA-20260929:L171–207,529–541; Q:harbor-harness.md#H05 |
| AR-036 | 2,3,4,5,6 | 必须具备目标 Harbor 实际端到端材料：版本、同一 trial 配置、移交、独立环境、reward 与日志。无正式 Hidden 权限可用授权自验数据；仅 Docker 组件或静态检查不能称 Harbor 已通过。 | T:PCA-20260929:L529–541; Q:harbor-harness.md#H06 |
| AR-037 | 4,5,6 | 固定 Codex+GPT-5.6 Sol 与 Codex+Seed 2.1 Turbo，同任务/Prompt/公开协议，独立输出。推理档位默认各 provider 实际支持的最高有效档位，不能只把字符串写为 max 或静默降档。 | T:PCA-20260929:L569–618; Q:implementation-policy.md#QA18 |
| AR-038 | 4,5,6 | 两轨默认各至少 10 小时净有效执行，分别核算，排队/安装/构建故障/阻塞不计；本新版不主动采用 7 小时例外。外部异常仅可恢复原会话，不拼接新会话。 | T:PCA-20260929:L70–72,569–618,809–825; Q:implementation-policy.md#QA16 |
| AR-039 | 4,5,6 | 每轮是真实方法闭环而非环境排障/重复空转；最终是否超过 B 与轨迹是否有效分别判定，无提升不自动失败且须如实解释。 | T:PCA-20260929:L549–563,598–646; Q:implementation-policy.md#QA18 |
| AR-040 | 4,5,6 | Agent 逐轮自写八字段 round/policy_name/method_summary/status/score/failure_reason/retained_best/time，最终两份 JSON 顶层 rounds。score 是 Public/Dev 原始指标，失败未出分为 null；成功 ok 且原因 null；完成时间 YYYY-MM-DD HH:mm:ss，不替代有效时长。不另加日志字段。 | T:PCA-20260929:L620–646,829–874; Q:implementation-policy.md#QA21 |
| AR-041 | 5,6 | 只交唯一 best_method 完整代码/配置，不含模型或历史版本；依协议复验。每轨结束前复测当前最佳并将代码及必需模型/配置恢复至 /workspace/solution，artifacts 只传此候选。必要模型不得遗留未移交缓存。 | T:PCA-20260929:L557–559,660–668,878–884 |
| AR-042 | 6 | 三类最终目录职责不变，专家证据含说明、唯一方法、标注 JSON、摘要和两条轨迹。最小充分交付，不把全部探索材料或内部流程账本机械列为必交。 | T:PCA-20260929:L670–730; Q:submission-format.md#1/#3 |
| AR-043 | 6 | expert_annotation 载题目、指标与同协议锚点及隔离声明；中文专家说明补双镜像 context/命令/不可变标识、目标 Harbor 版本/实跑、候选权限和 Hidden 授权方式，不自称平台通过。 | T:PCA-20260929:L722–807 |
| AR-044 | 6 | run_summary 如实写两轨净有效时长与实际轮数；image 仍仅 Agent 镜像。例外资格键 non_training/short_iterations 不使用时为 null；当前流程坚持各 10h，不自动启用 7h。Verifier 信息放专家说明。 | T:PCA-20260929:L809–827; Q:implementation-policy.md#QA16/QA21 |
| AR-045 | 6 | 最终 QA 只对确定版本提交包取证：先 G01–G03，再 QA01–QA21 和 H01–H06；明确失败与缺证分开，QA15 按 Skill 跳过，平台独有项不写已通过。 | T:PCA-20260929:L74–78,886–952; Q:SKILL.md#工作流程/#覆盖边界; Q:implementation-report.md |
| AR-046 | 6 | QA 报告须覆盖所有适用项与决定性子条件、证据路径及修复/验收条件；返修后新包必须重新独立质检，旧报告不能移植。 | T:PCA-20260929:L74–78; Q:implementation-report.md |
| AR-047 | 1,2,3 | 资源协议核对任务卡；教程给出的通用边界为 CPU ≤64C、单 Job 默认 GPU ≤8，单次改动到 Public/Dev 出分尽量 ≤2 小时。无法通过压缩达到目标时记录原因并交平台复核，不默默提高预算。 | T:PCA-20260929:L171–207,529–543 |
| AR-048 | 2,3,4,5,6 | 两套镜像各自依赖自足；最终评分不依赖 Agent 临时安装、缓存或未移交文件。依赖可追溯、体积受控，真实目标 Harbor/profile 可用，不照搬题目样例资源。 | T:PCA-20260929:L288–324,455–464; Q:harbor-harness.md#H03; Q:source-alignment.md#本次明确裁定 |
| AR-049 | 2,3,4,5,6 | Train/Public/Dev 指纹与切分固定；公开及正式指标/约束对齐但分别绑定 split 与 B/U 标定，不把 Dev 值称 Hidden。私有资产按授权交付给 Verifier/平台，不能错误复制给 Agent。 | T:PCA-20260929:L144–165,294,455–464,515–525 |

## QA v0.3.1 后续同步

2026-09-30 已读取项目方 v0.3.1，详细裁定见 [QA 同步说明](../AutoResearch新流程/QA_V031_ALIGNMENT.md)。上文为 PCA 初次升级记录；最新逐条投影以 rules/catalog.json 为准。QA06/09/10/17 无旧口头豁免。H05/H06 的静态不适用与教程真实自验分别记录，NOP 推荐、Oracle 可选。新增 AR-050 追溯 Q:exposure-manifest.md；H03/QA17 逆向覆盖纳入该规则。当前规则共 50 条，覆盖 G/B/QA/H 共 38 项。
