# 旧批次格式／配置迁移：实际旧新版来源对照

**采用用户最新口径：本批旧题只做格式和配置迁移，不要求重跑。新增标准造成的旧记录缺口可豁免，范围包含网络、镜像、布局和版本关联，不再限定GPU。**

此前“原来没有NOP或哈希就绝不豁免”的结论，建立在把v0.3.10当原标准的错误前提上。实际phase2默认实现明确允许H06无材料不适用、QA15跳过、轨迹每轮仅两字段，也没有四项task_binding必填。

## 实际来源及证据限度

- 旧基准：`autoresearch-qa-skills.zip` 中的 `autoresearch-task-qa/` 安全提取件（2026-09-30留存），原包SHA-256 `d91c08500b49bdc3e5050426be84af65538806aeecc18d2dcefc4243aeb5d5a9`。只比较默认implementation，不混用旧strict专项规则。
- 新基准：本次提供的原始 `autoresearch-task-qa/`，对应exact `review_skill-0.3.10_1015(1).zip`。
- 可用V3教程rev41、rev222仍有storage_mb/no-network配置示例，GPU写“优先”；这说明后来的MASO配置禁令与目标平台迁移不同于旧示例。
- 这些V3快照已要求八字段，而phase2 Skill仍写两字段：属于当时来源与执行口径未同步。原教程P1J5...rev221只有来源记录，没有找到其全文，不能伪称已核全文。
- 资源目标原算法已有，但旧QA15不审；科学B/R有效性和预算公平原本仍审。

## 有限新增要求矩阵

| 新增／收紧项 | 旧→新证据 | 本批处理 | 不随之豁免 |
|---|---|---|---|
| D01 NOP从可不适用变为必交 | 旧：没有Harness材料时H06可not_applicable并注明未验证；不强制新增运行，更不要求必须使用nop。 新：必须当前版本NOP；缺记录使H06/QA17失败；另核agent=nop、separate、结束状态、reward及同次材料。 | 本批若原来没有NOP，或只有合法Oracle/普通Harbor历史运行，也可免为新标准新增NOP；不能再把“此前未NOP”本身列为绝不豁免。无运行记录应如实标未运行。 | 已经提供的异常、坏reward、错误任务、伪造记录不能改写成成功NOP。纯新格式差异可免重做，但已有材料仍按实际含义审，不认证本次运行。 |
| D02 每轮两字段变八字段及分数/失败/best审查 | 旧：默认phase2明确每轮仅round、method_summary；结果、模型和时长从其他真实材料交叉核对。 新：要求八字段，并加强分数、失败原因、最佳标记、时间等逐轮结构/关联审查。 | 免为旧轨迹倒填六个新增字段、补造逐轮分数/时间/失败记录或重跑。可保留旧轨迹并读取已有等价材料。 | 确实少一条独立轨迹、另一题冒充、真实记录相互矛盾、已确认造假并非八字段新要求。有效10h/7h要求原本存在。 |
| D03 四项题包指纹及run_summary.task_binding | 旧：phase2默认核心JSON/JSONL只要求可解析、真实核心内容及相互一致；没有四项task_fingerprint机制或task_binding必填。 新：run_summary记录hash_profile/task_content_sha256，重算environment、task.toml、tests、instruction；缺字段manual、冲突fail。 | 原本无四项哈希、无旧快照，或本次合法格式/配置迁移导致新旧指纹不同，都可作为新增绑定缺口豁免；不得要求先补“原绑定本就有效”才可豁免。能无执行计算的当前指纹可供平台记录，不假称历史研究用过它。 | 若有确证表明结果属于另一任务、历史哈希被伪造、实际方法/数据/评分被调换，属于真实来源问题；不能靠新字段豁免掩盖。单纯指纹不同本身不能证明业务变更。 |
| D04 QA15从跳过变成必查资源与硬件比较 | 旧：QA15强制skip；但规范文档已有资源目标，Baseline公平预算和题面约束仍在旧G02/QA05检查。 新：必查有依据的完整单轮≤2h、≤8GPU、≤64CPU估算与H20/L20迁移影响。 | 免为本批新增资源估算记录、目标卡实测、耗时/锚点换卡复验和由此派生的正式成绩待核；有旧日志就使用，不强制补跑。当前配置仍按平台规则迁移。 | 已有证据证明原B/R预算不公、挑选种子或伪造硬件标签，不因旧QA15跳过而失效。当前明确错误的配置须修，不用豁免替代格式修复。 |
| D05 GPU优先卡型变为当前内场限定卡型 | 旧：旧算法文档rev1724和V3教程快照写优先H20/L20；phase2不将当前MASO卡型作为统一自动否决门槛。 新：内场GPU只用H20/L20；CPU题不加GPU；要求区分旧卡实测与目标卡结果/估算。最新教程V4 revision51明确候选列表可保留其他型号，只要支持并实际选用H20/L20；原0.3.10的列表整体否决作为兼容差异单列处理。 | 改目标配置即可，免重跑原研究和B/R。旧卡成绩继续标原卡，不能为满足新格式而改标签。 | 当前目标配置本身仍需迁移；不得写成新卡已实测。原来就不同硬件混用锚点导致科学不成立，不能只按QA编号豁免。 |
| D06 禁网/白名单/磁盘配置失效及新联网场景约束 | 旧：旧QA05有环境限制或verifier逻辑即可；按目标provider判断，旧V3配置示例直接给storage_mb与no-network。 新：默认MASO不支持这些字段；删字段后仍要求题面和可信评分在联网条件下成立，缺新约束落实/证明会派生失败。 | 当前配置移除未支持字段。按用户本轮明确授权，删除禁网后联网/外部查表约束未落实等新场景派生缺口，也纳入本批豁免；不要求为此新增实验、防查表机制或重跑后才给豁免。如实列目标联网场景尚未验证。 | 已确认实际读取Hidden/标签、查表作弊污染已提交结果、伪造得分或原代码故意篡改评分的事实不免；“当前新增防护未证实”不能直接写成已经发生泄漏。 |
| D07 镜像预构建/依赖自足及不同sandbox | 旧：允许目标provider使用Dockerfile、Compose、预构建镜像或适配；不强制依赖预构建/数据预置/禁止挂载。 新：显式separate、不同sandbox、实际镜像选择分支、独立依赖、tests上传/预置和artifacts合同。 | 只做必要目录、Dockerfile/镜像配置、入口及依赖清单适配；免为新镜像、双sandbox、依赖独立性、实际产物移交补当前运行记录。旧包没有两套Dockerfile不是必须重跑的理由；按实际分支可复用镜像。 | 格式修复后确实缺入口/源码、COPY物理缺源、必需依赖未声明或静态路径不成立仍须修；字节内网镜像准备/实际运行不转为专家新增权限要求。 |
| D08 Compose/额外工作环境及构建上下文 | 旧：有依据的Compose和task-root教学profile允许，不能混用上下文；旧实际路径错误仍失败。 新：正式environment/tests直属Compose禁止；每sandbox单容器、不调用额外工作环境；默认environment/tests独立上下文。 | 迁移/删除不适用Compose及旧上下文并完成可静态核对的格式修复；免因这些格式配置改变而要求重新生成旧研究/Trial。迁移后的平台运行能力列待验证。 | 当前目标配置仍正式依赖被禁止Compose/额外工作环境不能称已完成格式迁移；物理缺文件与真正调用错误须修，不靠保留旧报告改为通过。 |
| D09 Job/Trial配置和版本/运行关联 | 旧：H05有配置才核对；没有且不声称运行时可N/A；单任务CLI有效，不强制job.yaml。 新：H05仍不是job.yaml必交，但当前NOP/innerfield配置、版本、sandbox和覆盖需要交叉核对。 | 免新平台/迁移后的Job/Trial、版本关联与重跑材料；不以没有新NOP或旧配置不能证明当前MASO运行而重复降级。保留现有材料真实身份和未实跑状态。 | 已有配置中明显错误任务/路径、禁用评分器、损坏配置仍按静态格式修；不能把Oracle日志改称NOP或把Native旧运行写成当前MASO实跑。 |
| D10 研究质量、原正式证据和真实行为边界 | 旧：原本已有方法级优化、合理Baseline、全部正式seed、真实成对日志、条件性模型/重载、[0.15,0.8]归一化及3σ、真实独立轨迹与时长。 新：核心科学门槛仍在；增加硬件/行为/版本关联的审查分支，不等于全部科学要求都是新要求。 | G03/QA03/QA13仅解除由新平台、新卡、新网络、NOP或版本记录缺口派生的降级；可用原材料完成静态复算，不要求重跑。 | 已确认原始值不达门槛、真正不公平/无效对照、缺原标准就要求的Reference/正式seed/原始结果、真实造假泄漏等，不凭截图编号整项免；未知不推定作弊。 |

## 矩阵定位依据

- D01：旧 旧版 `references/harbor-harness.md:28`；旧版 `references/implementation-policy.md:23`；新 新版 `references/harbor-harness.md:42`；新版 `references/harbor-harness.md:56`。
- D02：旧 旧版 `references/implementation-policy.md:27`；旧版 `SKILL.md:55`；新 新版 `references/implementation-policy.md:27`；新版 `references/implementation-policy.md:24`。
- D03：旧 旧版 `references/implementation-policy.md:27`；新 新版 `references/implementation-policy.md:27`；新版 `references/runtime-integrity.md:18`。
- D04：旧 旧版 `references/implementation-policy.md:21`；旧版 `scripts/implementation_review.py:549`；新 新版 `references/implementation-policy.md:21`；新版 `references/innerfield-deployment.md:13`。
- D05：旧 旧版 `references/implementation-policy.md:21`；新 新版 `references/innerfield-deployment.md:13`；新版 `references/implementation-policy.md:21`。
- D06：旧 旧版 `references/implementation-policy.md:11`；旧版 `references/harbor-harness.md:25`；新 新版 `references/innerfield-deployment.md:14`；新版 `references/implementation-policy.md:11`。
- D07：旧 旧版 `references/harbor-harness.md:25`；旧版 `references/implementation-policy.md:23`；新 新版 `references/harbor-harness.md:39`；新版 `references/innerfield-deployment.md:15`；新版 `references/harbor-harness.md:31`。
- D08：旧 旧版 `references/harbor-harness.md:25`；旧版 `references/harbor-harness.md:17`；新 新版 `references/innerfield-deployment.md:15`；新版 `references/harbor-harness.md:39`。
- D09：旧 旧版 `references/harbor-harness.md:27`；旧版 `references/harbor-harness.md:28`；新 新版 `references/harbor-harness.md:41`；新版 `references/harbor-harness.md:42`；新版 `references/harbor-harness.md:56`。
- D10：旧 旧版 `references/research-quality.md:41`；旧版 `references/research-quality.md:42`；旧版 `references/implementation-policy.md:9`；旧版 `references/implementation-policy.md:24`；旧版 `references/implementation-policy.md:22`；旧版 `references/implementation-policy.md:31`；新 新版 `references/research-quality.md:41`；新版 `references/implementation-policy.md:24`。

## 截图11项的有限豁免

| 编号 | 判法 | 可以豁免 | 仍按事实处理 |
|---|---|---|---|
| G03 | 逐原因豁免新标准派生的有效性降级 | 新硬件/新平台/联网场景未复验；新增版本绑定或运行关联缺口 | 按原数据可复算且本来不达标的数值/公平性问题 |
| QA03 | 沿用旧正式Reference，免新复跑 | 新卡/新平台复跑与新关联记录 | 原标准已有的参考实现、正式seed结果和条件性模型证据 |
| QA05 | 用户明确允许新联网场景派生缺口豁免 | 删禁网后联网/外部查表约束未落实；新平台约束效果/新运行验证缺口 | 原就存在的核心评分实现故障；已确认真实作弊/泄漏污染 |
| QA13 | 保留原成对比较，免迁移复验 | 新卡/新环境下的对照复验与效应比较 | 原来不完整或不公平的B/R证据 |
| QA15 | phase2本来跳过；免本批新增资源记录 | H20/L20实测、代表性重跑、额外资源/耗时/锚点比较记录 | 当前目标资源配置应完成适配；旧研究的公平预算与事实真实性 |
| QA17 | 按子原因汇总豁免，不整行自动通过 | 获准H项造成的严格汇总fail/manual | 未豁免的静态格式/科学缺陷 |
| QA21 | 可免原本无新哈希及六个新轨迹字段 | 旧轨迹只含两字段；原本没有四项task_binding；迁移导致新旧指纹变化/无旧快照 | 旧核心JSON/JSONL真实可解析；实际另一任务冒充/伪造旧哈希等确证问题 |
| H02 | 改配置；新平台运行/能力证明缺口可免 | 新平台配置生效记录；新网络场景约束有效性关联 | 当前有效配置应去除不支持字段并可静态解析 |
| H03 | 改镜像/路径组织；不要求补运行证书 | 新镜像/新sandbox运行证据；新独立依赖/实际移交验证记录 | 当前缺文件/静态路径错误须修；原有实际源代码故障 |
| H05 | 新Job/Trial配置记录可免 | 新平台/迁移后调用覆盖与关联记录 | 现有配置的实质错误须修；不伪造旧provider运行身份 |
| H06 | 原无NOP也可免新增NOP，不仅免重复NOP | 原来未NOP；只有非nop的合法历史运行；迁移后无当前版本NOP | 旧记录不改称成功NOP；提供的真实异常/造假仍如实审 |

## 实施时不能重新收窄的边界

- 不能要求必须先有旧NOP/旧四项task_binding才允许本批豁免；phase2未统一要求这些材料。
- 不能把自动核验只会识别两侧gpu_types纯变更当作业务豁免范围；本轮明确包含网络、镜像、布局和配置迁移。
- 不能以新增字段缺失推断造假；不要求倒填六个轨迹字段、补造历史哈希或重做研究。
- 不能把用户已明确允许的联网/外部查表新场景缺口继续列为绝不豁免；也不能将缺新防护等同实际发生泄漏。
- 当前格式/配置修复与历史研究复验分开：该修的文件/配置修，不追要求新实验日志、NOP或目标卡成绩。
- 保留严格新标准原判并另外解释旧批次例外及平台待验证事项，不宣称已实跑、已安全隔离或已测新卡。
- 科学门槛/结果造假/确认泄漏等按事实处理；同一QA编号有新增缺口与原有失败时拆开，不整项免。
- 本分析不授权抹去真实算法/数据/评分业务变更；纯格式/配置迁移不必提供原先不存在的快照/hash才能进入人工豁免核对。

## 例子

- 旧题原来没有NOP、没有task_binding，轨迹只记两字段：这些不是自动证明原题不完整；本批可免新标准补交，不重跑，不倒填。
- 旧题按原provider的no-network限制研究，迁移MASO删字段后缺联网防查表机制：按用户本次明确授权作为迁移派生缺口豁免，写尚未验证；不能再要求补新机制后重跑才获免。
- 旧题本来Reference只有0.09归一化、原始值不足3σ、混用了不同硬件锚点，或已确认Hidden查表污染成绩：这些是原有科学／真实性问题，不能因为对应G03/QA03/QA13就整项免。
- 旧Dockerfile需要从task-root迁到environment上下文，Compose需要改为平台接受的交付：修可静态检查的格式／配置；不要求专家因此重新跑10h研究、新NOP或B/R对照。

## 可移植的原文摘录

以下仅保留本次规则对比所需摘录，不作为任何具体题目已通过的证据。

- 二期 `SKILL.md`："QA15仍跳过平台资源上限检查"；"每轮仅round与method_summary即可"。
- 二期 `references/harbor-harness.md` H05："未提供调用配置且不声称已有运行时可不适用"。
- 同文件 H06："无材料则不适用并明确‘未验证运行’"；"H01–H04必查，H05/H06仅符合上述条件可不适用"。
- 二期 `references/implementation-policy.md` QA17："无已有Harness运行证据不强制新增执行，但必须标注未验证运行"。
- 新版 `references/source-alignment.md`："两条Agent轨迹按三期教程记录八字段"；"以上替代历史跳过QA15"；"缺少记录使H06与QA17fail"。

新增要求在不同旧批次生效时间不完全相同，不能把phase2 Skill等同全部历史文档。可用V3快照已有八字段，与旧Skill当时不同步。本批最终按用户统一的格式迁移、不重跑授权处理，仍如实说明该来源差别。
