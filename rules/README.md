# 当前要求：按需查阅

这是执行用的精简索引，不是第三个权威来源，也不是每题填写的检查表。先读本节口径，再按所用 Skill 的链接读取相关条目；有歧义或需要字段细节时回查原件。不为每个动作重算全库锁或复制一套报告。

## 来源与适用口径

| 优先级 | 当前原件 | 版本与定位 |
| --- | --- | --- |
| 1 | [专家线下标注教程][T] | PCA 双镜像对齐版，2026-09-29；下文用章节名定位 |
| 2 | [项目方任务 QA][Q] 及 [Baseline 专项][B] | 默认 QA v0.3.2（2026-10-03）；Baseline 沿当前配套原件，不虚构独立版本号 |
| 限定例外 | 用户明确通知 | 只在明确范围内采用；不是旧通知全部继续生效 |

完整原件、版本与哈希已在 [manifest.json](manifest.json) 保留。使用默认 implementation 口径，不混入仅按明确要求启用的 strict；QA15 当前跳过，其余旧口头 QA 豁免已撤回。[来源裁定][A]

**已确认的用户工作约定，区别于项目方原文：**最终未提升不自动失败，前提是 B/R 正确，且不是缺工具或环境问题；不豁免真实独立迭代、时长、日志和合法性。取消专门 12h 容器浸泡门禁，不声称未做的稳定性测试通过。仅最终唯一方法正式复验；最终 QA 由用户在独立会话进行。三包 ZIP、七项填表和轻量工作记录属交付/协作约定，不升级成额外科学门槛。

研究 → [M01](#m01)、[M02](#m02)、[M04](#m04)；实现 → [M05](#m05)–[M07](#m07)、[C01](#c01)–[C06](#c06)；实验 → [M02](#m02)–[M04](#m04)、[M10](#m10)–[M11](#m11)；迭代 → [M08](#m08)–[M09](#m09)；交付 → [M09](#m09)–[M13](#m13)、[C07](#c07)。编号只用于引用，不表示需要逐项登记。

## M01

**真实方法空间。** 题面、接口和 guard 真正允许可编程方法改进，不能只是固定方法找数字。Reference 变化小不单独构成纯调参，须核实际空间与代表性；至少留一种题面未直接提示的合法改进方向，不要求穷尽搜索或实证最优解。来源：[研究门槛][G] G01、[默认 QA][I] QA14；[T]「出题模式与输入」「评分锚点与公式」。

## M02

**正式 Baseline 合理。** 默认用正确可运行的未经修改 Starter；只有 scaffold 时另提供可解释、合理且可运行的朴素对照。评分 B 绑定正式聚合值，不能另取弱零点。验证后 B/R 共同冻结；适用的 B01–B08 须有证据支持，依赖后续结果的判断先待验，不能提前写通过。直接复用 [Baseline 专项][B]，不另造审查制度；不要求 SOTA，不凭方法简单、年代或差距大判失败。来源：[T]「Baseline 训练充分性与方法代表性」；[G] G02。

## M03

**独立、完整、公平复验。** 运行前确定数据、切分/指纹、指标、预算、正式 seed、重复/聚合及选择规则；B/R/待评方案同口径。随机评估正式协议未规定时至少各 3 次独立运行，波动大至少 5 次；已声明五个 seed 就保留全部五组，成对比较，不挑有利 seed、不用同一 checkpoint 重复评估冒充独立训练。研究变量可不同，但共同预算和匹配控制须公平。确定性适用性须有依据，固定 seed 不等于确定性。来源：[T]「优化面、Baseline 与 Reference 训练证据」「随机性与可分辨性」；[B] B03–B05/B07；[I] QA04/13。

## M04

**改善与评分有效。** 从全部有效正式结果复算均值及 `n−1` 样本标准差。随机任务正向改善 `Δ>0` 且 `Δ≥3σ_B`；3–5σ 可接受，按教程增加重复并标平台复核，≥5σ 为强证据。确定性须真实正向改善，不套已删除的统一 5% 门槛。质量门须同时满足。

归一化 B=0、预计可达上限 U=1，连续单调、方向正确、不裁剪；R 不作固定锚点，自验 Public/Dev 正式归一化应在 [0.15,0.8]。maximize 用 `(x-B)/(U-B)`，minimize 用 `(B-x)/(B-U)`；U 位于正确方向且不等于 B，不能按目标分数反推，无可靠估计时有依据地用 Metric Ceiling。R 未饱和，剩余 headroom 的 3σ 是原则性风险复核，不擅自增加一刀切门禁。正式 Hidden 由平台复核，不把 Dev 值称 Hidden。来源：[T]「评分锚点与公式」「随机性与可分辨性」；[G] G03；[A] 当前裁定。

## M05

**实际可见性。** Agent 可用题面、Starter、公开数据/Dev 评分及本轨合法输出；不能看到私有 tests/Hidden、Reference、参考分数、汇总专家证据或另一轨内容。核真实镜像层、挂载、日志、环境变量和可读权限，不凭目录名判断。候选在 Verifier 内仍不可信，不能借 grader 权限读取私有标签或伪造 reward。

Agent 视图窄于作者包时，按 [exposure manifest][E] 在 `workspace/qa_exposure_manifest.json` 描述公开/可写/可信路径、双镜像标识、真实视图清单及核验身份；不能编造镜像探针记录。只选择满足边界的实现，不每题固定 Broker/chroot。来源：[T]「数据隔离与防作弊实现」；[H] H03；[E]。

## M06

**硬约束实际生效。** 教程要求题面限制由环境或评分逻辑执行；默认 QA05 核核心约束存在真实实现，不要求逐条映射签字或全套负向测试。冻结面有只读、可信恢复或校验保护；不用独立 digest 文件也可满足，不只靠文字禁令。QA15 跳过不豁免公平预算或题目硬约束。来源：[T]「错误与 Hard Gate」；[I] QA05/10/15。

## M07

**原生评分及 NOP。** 显式 separate、双镜像、公开反馈、候选移交和独立 Verifier/reward 链路真实可用。必交当前题包版本一次 NOP 的同一 Trial 配置、结果、reward 和日志，正常结束且无评分接口异常；放 `expert_evidence/`，版本对应可用已有说明，无须额外审批文件。可复用平台同版本记录，0 分不单独失败；早退 NOP 只证明该分支，不替代有效候选评分。Oracle 可选。来源：[Q]、[H] H01–H06；[T]「task.toml」「tests 与评分校验」。

## M08

**双轨真实运行与净时长。** Codex＋GPT-5.6 Sol、Codex＋Seed 2.1 Turbo 使用同题、同 Prompt/公开协议和相同资源口径，各自独立上下文/输出/运行实例；推理档位使用各模型实际支持的最高有效档位，不仅写配置字符串。默认各净有效 ≥10h。仅不训练/微调且单轮很短时，可在启动前选择各 ≥7h：每轨至少 3 个有效方法闭环、连续演进、后续方向、最佳方法干净重跑，以及完整资格和净时长证据缺一不可。不得事后为不足时长降格。

排队、安装、构建故障和真实阻塞扣除；两轨不相加，重叠区间不重复计，不能仅用首尾时间戳或原生计数代替净时长。保留实际操作/输出/作业与中断恢复依据供包内复算。来源：[T]「模型组合与执行时长」；[I] QA16/18。用户约定：外部异常只续接原会话/原 Goal，不拼接新会话，不干预正常自主收口；没有最终提升按本页限定例外处理。

## M09

**轨迹由迭代 Agent 生成。** 运行期 JSONL 每行一个真实轮次，最终为 `{"rounds": [...]}`，不是原始终端日志或 ATIF。每轮八字段：`round`、`policy_name`、`method_summary`、`status`、`score`、`failure_reason`、`retained_best`、`time`。顺序从 1 递增，摘要 1–3 句，成功 `ok` 且原因 null，失败保留真实原因/未知分数 null；成功分数有限，最佳标记布尔，时间可解析并按教程格式表示完成时刻。

`score` 是对应 Public/Dev **原始指标**，不是 Hidden/归一化分数；最佳标记按指标方向核对。允许有原始依据的格式或摘要修正，不编造轮次、方法、分数和时间。模型及净时长在摘要/专家说明，不增加每轮字段。来源：[T]「每轮记录方法迭代字段」「trajectory_seed.json 与 trajectory_codex.json」；[I] QA18/21。

## M10

**唯一最终方法。** 比较两轨同口径有效结果，选唯一 `best_method/`，完整代码/入口/必要配置在干净快照同协议复验；最终方法重复口径按 M03，不默认两候选各五次。运行期两轨结束前各自重跑并恢复最佳候选及所需模型/配置至提交面；`best_method/` 只交代码，不放 checkpoint 或历史快照。模型按任务合同另确保可移交、加载。均未超过 Baseline 时如实解释，不伪造正分或改交 Reference 冒充 Agent 解。来源：[T]「整理最终最佳方法」「best_method/ 交付要求」；唯一最终方法正式复验范围及无提升处理为用户已确认约定。

## M11

**必要训练证据齐全。** `optimization_evidence/` 含中文 `训练证据说明.md`、B/R 全部正式 seed 的 `result.json` 与原始非空 `run.log`、`comparison_summary.json`。训练型每轮有真实模型、`model/artifact.json` 和干净进程重载复评分的 `reload.log`；非训练如实 NOT_APPLICABLE，不造空模型目录。保留失败日志，不能用复制模型或手工摘要冒充原始训练。

结果绑定真实方法/依赖哈希、协议、执行、指标/质量门、相对包根路径及产物；汇总从逐次值复算，只有全部规定运行有效且必要模型验证完成才 COMPLETE。缺失历史命令/时间/退出码填 null 并解释，不反推。过大模型走平台认可的不可变入口。来源：[T]「优化面、Baseline 与 Reference 训练证据」；[F] §2；[I] QA03/13。

## M12

**最小充分提交。** 三目录职责：`workspace/{harbor_task,reference}` 为完整可执行题目及专家参考；`expert_evidence/` 含中文专家说明、expert_annotation、run_summary、两轨 JSON、唯一 best_method 及必要 NOP/复验/时长/隔离证据；`optimization_evidence/` 只放 B/R 主证据。必要取证在最终包内可追溯，不靠包外目录。

题面八部分有实质内容且不泄露论文标题/arXiv/repo 来源、Hidden 答案或 Reference 细节；按教程八标题填写，QA 接受语义等价。专家说明按教程内容组织，源码、题面、轨迹和 JSON 不残留旧题/旧协议。用户约定：不提交纯流程审批、状态账本和返修对比；有用额外证据保留，实际失败研究事实不抹去。来源：[T]「instruction.md」「最终交付结构」「专家作业说明文档」；[F]；[I] QA01/07/08/11/18/21。

## M13

**独立 QA 后直接交付。** 用户在新会话用 [Q] 审指定最终包，制作 Agent 读终稿返修；适用项全部通过且复核完成，不把收集器初稿当 PASS，不向 QA 提供包外补证。影响结论的变更要核受影响部分并重新独立审对应包；无关实验不自动重跑。来源：[Q] 工作流程与总评；独立会话和仅包内取证为用户已确认边界。

用户交付约定：通过后直接以 `package_root`、`qa_report`、包外 `output_dir` 打完整包、其中 harbor_task、optimization_evidence 三个 ZIP；默认上传上限 300,000,000 字节、分卷 290,000,000 字节，按表单可调整，超限才分卷。UTF-8 名称及必要权限可恢复。输出目录写七项中文填表信息，缺项据实待补；不新增 qa_bind、阶段关闭或打包审批。源包未变的压缩/包外填表不重复 QA。

## C01

**结果防伪。** 可信评分前清理候选可能预写的结果，实际计算并原子替换 reward；不能采信候选自报分数。不额外强制 fsync、唯一临时文件名或完整竞态测试。来源：[T]「数据隔离与防作弊实现」；[I] QA09。

## C02

**Git 线索条件性清理。** Agent 可见内容没有 `.git` 时不另造清理；有则核 remotes/tags/reflog 和明显答案修复线索的清理结果或实际实现。只有脚本就说存在实现，不谎称已经清理。专家研究 Git 保留正常检查点，不因 QA12 删除。来源：[T]「数据隔离与防作弊实现」；[I] QA12。

## C03

**题面不能遗漏。** 随机任务在 instruction 中说明 seed 和有效提升阈值（如按 B 原始指标样本标准差的 3σ 判据）；“不能挑 seed”不等于说明阈值。按教程声明 repeat/聚合政策，默认 QA19 本身不强制额外列出全部次数，但已声明正式 seed 的证据必须齐全。题面同时明确网络、检索/工具、可改可写和并发政策，引用平台策略须对象明确。来源：[T]「instruction.md」「提交前专家自查」；[I] QA19/20。

## C04

**入口与 reward。** 沿单命令和实际必填参数验证评分调用，不假定 cwd 为 `/tests`。输出 `/logs/verifier/reward.txt` 有限标量或 `reward.json` 非空有限数值对象，两者并存优先 JSON；stdout、自定义 result.json 或 pytest 不能替代。格式、Hard Gate、超时、资源及基础设施失败分类，非作弊 Hard Gate 返回 -1 表示无效、不参与正常排序；不能将所有异常装成 0/-1。来源：[H] H04；[I] QA06；[T]「错误与 Hard Gate」。

## C05

**双镜像路径与产物移交。** 默认 Agent Dockerfile/context=`environment/`，Verifier=`tests/`，各自依赖自足；核 COPY/ignore/WORKDIR/入口/实际权限。Hidden 的文件、生成或安全注入必须有来源和真实调用，不造空目录。`task.toml` 显式 `[verifier] environment_mode="separate"`，artifacts 仅移交候选与必要模型/配置，Verifier 保持源绝对路径，destination 不是容器重映射。源码 `solution/` 是可选 Oracle，不等于运行时 `/workspace/solution`。来源：[T]「Docker 路径契约」「task.toml」；[H] H01/H03；[D]。

## C06

**目标版本配置生效。** 完整 TOML 的位置/类型及原生 schema 或真实适配与目标 Harbor 版本一致，不能只证明语法可解析。存在 Job/Trial/CLI 配置时核 task/provider/agent、覆盖与启动条件、Verifier 未禁用、无路径/重复键冲突；无配置不强造 job.yaml。静态审查与实际运行分开报告。来源：[H] H02/H05；[D]。

## C07

**字段格式按当前原件。** 两轨根结构/八字段见 M09；`expert_annotation.json`、`run_summary.json` 按 [T] 同名章节及 [F]，不把 ATIF 或旧版字段混入。run_summary 的 image 仍为 Agent 镜像，Verifier 标识/实跑写专家说明；7h 资格和实际时长据实一致。

每轮 B/R `result.json` 顶层至少有 `schema_version, status, role, seed, task_type, method, protocol, training, execution, metrics, quality_gate, artifacts`；核类型/适用性、真实 seed、路径/哈希和摘要一致性，不只检查存在。当前程序未覆盖的语义仍需阅读证据。来源：[T]「expert_annotation.json」「run_summary.json」；[F] §2；[I] QA21。

## QA 项目到本页的映射

用于维护查漏，不是另一次 QA 或每题填写表。B 专项的八项分别沿原 Skill 执行；QA15 只保留当前跳过口径。

| 当前项目 | 本页落点 |
| --- | --- |
| G01 | M01、M05 |
| G02、B01、B02、B03、B04、B05、B06、B07、B08 | M02、M03、M11 |
| G03 | M03、M04、M11 |
| H01 | M05、M07、C05 |
| H02 | C06 |
| H03 | M05、M06、C05 |
| H04 | C01、C04 |
| H05 | C06 |
| H06 | M07 |
| QA01、QA07、QA08、QA11 | M05、M12 |
| QA02 | M04 |
| QA03 | M04、M11 |
| QA04、QA13 | M02、M03、M04、M11 |
| QA05、QA10 | M06 |
| QA06 | C04 |
| QA09 | C01 |
| QA12 | C02 |
| QA14 | M01、M04 |
| QA15 | 来源与适用口径、M06 |
| QA16 | M08 |
| QA17 | M05、M07、C04、C05、C06 |
| QA18 | M08、M09、M12 |
| QA19、QA20 | C03 |
| QA21 | M09、M12、C07 |

`catalog.json` 的 AR 编号及阶段 timing 暂供尚未解耦的旧程序使用，不是本入口要求用户履行的登记步骤；不同时执行两套流程。规则原件更新通过维护入口定位影响，不让每题重填来源或复审无变化内容。

[T]: ../sources/tutorial/AutoResearch%20专家线下标注教程｜PCA%20双镜像对齐版.md
[Q]: ../skills/autoresearch-task-qa/SKILL.md
[B]: ../skills/autoresearch-baseline-quality/SKILL.md
[A]: ../skills/autoresearch-task-qa/references/source-alignment.md
[G]: ../skills/autoresearch-task-qa/references/research-quality.md
[I]: ../skills/autoresearch-task-qa/references/implementation-policy.md
[F]: ../skills/autoresearch-task-qa/references/submission-format.md
[H]: ../skills/autoresearch-task-qa/references/harbor-harness.md
[D]: ../skills/autoresearch-task-qa/references/docker-path-contract.md
[E]: ../skills/autoresearch-task-qa/references/exposure-manifest.md
