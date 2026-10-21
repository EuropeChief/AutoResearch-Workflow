# 来源、版本与适用范围

当前流程执行副本以随包 V4 教程和 `review_skill-0.3.10_1015.zip` 为底稿，采用 [GPU通知](../../../sources/notices/2026-10-21-gpu.md)及[QA放宽通知](../../../sources/notices/2026-10-21-qa-relaxation.md)：实际GPU自选、最终配置H20；所列哈希/NOP/换卡补证仅提示。执行修订 `v0.3.10+project-notices.20261021`，官方ZIP原件保留。下文历史来源中相冲突的卡型及缺证硬门槛由这两项通知覆盖，其他要求继续适用。

本次 v0.3.10（2026-10-15）以用户提供的 `review_skill-0.3.9_1012.zip` 为底稿，只补充用户确认的容器组织与GPU使用要求：每沙盒单容器、直接使用当前沙盒GPU、禁止任务／Agent部署或调用额外工作环境，并保留平台创建独立Agent/Verifier、运行前构建、本地进程和正常模型／数据服务请求的边界。详细规则集中在[内场部署口径](innerfield-deployment.md)，沿既有H03→QA17复核；无关判定标准、作者schema和原Compose文件禁令不变。下段保留v0.3.9的来源记录，不表示本次重新读取其在线来源或复跑题目。

v0.3.9（2026-10-12）仅按用户本轮明确要求补充原始评分参照保护、时限阶段覆盖、种子实际生效与固定候选/同集合配对、题面到实现的要求冲突检查，并收紧默认 implementation 的 Compose 文件交付规则、统一显式证据定位校验；不新增作者必填 schema、不改旧 strict 路线。Compose 正式目录四文件名命中不因 generic-harbor、镜像或 unused 声明豁免，细则与扫描边界见[内场部署口径](innerfield-deployment.md)。保留 v0.3.8 的模型组合可调整口径：QA18 核对实际运行及独立性，不设固定型号或换模型审批门槛；保留自洽性修复、内场交付要求与既有业务门槛。教程核对快照为[专家线下标注教程V3](https://bytedance.larkoffice.com/docx/DJhEdv0oTod4sExGgu6cp00onHg) revision 332；本轮同步说明模型组合可调整，以及原题卡型与内场交付卡型的区别。此前镜像复用和训练／随机性范围澄清继续有效。另只读核对[MASO harbor-runner 指南](https://bytedance.larkoffice.com/docx/MOP9d9m57oMxN1xlBfecbXUtnWe) revision 1627：卡型配置、预构建镜像、禁网/白名单 warning 后降级联网、Compose 不支持与 separate 产物移交；storage_mb 暂不支持采用用户本轮明确要求，不误引为该指南条目。新增口径见[当前内场部署口径](innerfield-deployment.md)。保留既有内容门、NOP、轨迹、时长与四项哈希；下表为二期历史来源，只追溯未被替代条款。

| 来源 | 读取版本 | 采用内容 |
|---|---|---|
| [专家线下教程](https://bytedance.larkoffice.com/docx/P1J5dgIw1oKchcxn29GcvzlMnSd) | revision 221（修改前） | 三目录、成对全部 seed、条件性模型证据、两条简化轨迹、双轨各10h与7h例外 |
| [算法规范](https://bytedance.us.larkoffice.com/docx/Th1ydNXiXoa59lxJrg0uYSnlsdc) | revision 1724（修改前） | 方法搜索空间、合理非平凡Baseline、归一化[0.15,0.8]、Baseline样本标准差的3σ门槛、5σ强证据、Harbor接口与12h容器稳定性目标 |
| 教程顶部 example.zip，附件 Tc56bO51bokIHOxGXP5cgPbvn9g | 83,826,813 字节；2026-09-18读取 | 仅取经检查的文件布局和构建路径；其静态代码并不能证明目标平台已经构建成功 |
| 用户本轮明确要求及提供的算法侧交流 | 2026-09-18 | 拒绝固定任务纯调参；Baseline不得取不合理弱对照；允许无method Scaffold或合理naive Starter；前置方法介绍和三门判定；专家可执行退回说明 |

默认部署 profile 为 innerfield-maso-v1；实际GPU自选、最终配置H20，CPU题不增加GPU；当前不支持storage_mb、禁网/网络白名单与Compose。每sandbox必须单容器，不部署或调用额外工作环境，保留separate和不同sandbox；换卡补证按当前通知仅提示，不把旧结果冒充新卡。明确其他provider时可按其实际版本复核一般兼容性，不能称内场合规。

优先采用本轮明确要求和已核实的有效条款。资料矛盾要记录裁定与依据，不以旧报告、附件的passed或已删除旧文覆盖。今后用户给新任务卡/新平台规范时读取并更新版本依据，不把此快照当永久部署版本。

本轮采用的 _1012 包口径：显式 separate 且不同 sandbox；可以复用同一 Solver 镜像并运行时上传 tests，或使用专用 Verifier 镜像/构建预置 tests，不再一律要求双 Dockerfile。公开 Dev 必须保留供 Agent 迭代，最终私有 Hidden 留在独立 Verifier。Hidden 是私有测试用例、标签、基准或评估生成逻辑等，训练与非训练任务均适用；目录名可不同，也可有依据地生成或安全注入。检查材料、来源与真实调用关系，不要求固定非空 `tests/hidden_assets/`。这覆盖历史附件将全部 tests 复制进 Agent 的做法。

NOP已有记录用于说明实际构建及Harness分支，核正常结束、独立Verifier及reward，可复用平台记录。缺证或版本待核按当前通知仅提示，runtime_status如实记not_run/unverified；真实执行异常仍处理。版本可由已有配置/日志/专家说明关联，不强制新增哈希。NOP的0分本身不失败，Oracle非必交。官方 [Separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier) 说明独立环境及产物移交；[NOP 实现](https://github.com/harbor-framework/harbor/blob/main/src/harbor/agents/nop.py) 不执行求解操作，已有Starter并不会被清空。

## 本次明确裁定

- 算法规范中的“随机评分必须超出5σ”和“确定性超过Baseline 5%”均有删除线，已经废弃。生效的是3σ最低门槛、5σ强证据；确定性用真实正向改善、归一化范围及题目另行预声明容差。
- 当前教程主表、run_summary与启动Prompt已统一为两条各10h，支持完整证据下各7h例外；旧“12h且大于15轮”冲突已修复。7h只适用于不涉及训练且单轮迭代很短的任务。训练/微调任务即使单轮快也须10h，不自行定义通用分钟数界线。容器存活12h属于另一个稳定性目标，不能拿来替代Agent有效时长。
- 教程“Baseline=未经修改Starter”是默认。用户允许Scaffold不给method时仍须提交明确来源、可运行朴素对照和与归一化锚点的映射，不能以随机/故障/未训练占位分数造提升。
- 教程可改文件示例为method.py，不表示只能改数字；检查真正的接口与guard。方法结构固定而仅可调权重的题不通过。
- 当前默认 Agent 构建上下文为 environment/，专用 Verifier 构建上下文为 tests/；复用 Solver 镜像分支按目标版本上传 tests。历史 example Dockerfile 以任务根为构建上下文，容器根为/workspace，仅用于追溯或有适配证据的任务，不能混用。附件task.toml含自定义配置，test.sh只跑pytest，因此附件是布局示例，不是原生Harbor通过证书。具体适配实现必须查证。
- 提升空间Headroom的“原则上不少于3σ”应保留风险复核语气，不能升级为未声明的一刀切门槛。
- 两条 Agent 轨迹按三期教程记录八字段：round、policy_name、method_summary、status、score、failure_reason、retained_best、time；二期仅两字段的规则已被替代。有效时长仍从 run_summary 与实际记录核对，不能从时间戳跨度直接推算。ATIF 与专家轨迹不是同一 schema。

## 此Skill的静态覆盖边界

平台/专家的完整要求与自动静态质检的覆盖范围分开写。QA07/08仍审题面，QA18审所交轨迹行为与评分，QA21核对run_summary中的四项版本哈希；QA15结合已有日志、轨迹和B/R实现估算资源，有依据且符合上限即可通过，不强制每轮资源分配或生效限制证明。平台仍负责Hidden正式运行、完整物理隔离与资源/稳定性验证；本Skill默认不执行未知代码或12h压测。Baseline预算公平、可机检硬约束及构建接入属于G02/QA05/H03的在检范围。

格式扩展只要等价、路径有效、证据完整就不自动扣错；必需字段缺失及真实调用失败不能以“允许扩展”豁免。退回说明引用待检材料，不能把本来源说明当作专家任务已经运行的证据。

_1012 包规定哈希只覆盖 Harbor task 的 environment/、task.toml、tests/、instruction.md；递归全量文件和空目录。H06沿用已有配置、日志或专家说明的版本关联口径；严格哈希只在run_summary.task_binding的hash_profile/task_content_sha256两个字段记录，不强制新增启动记录。轨迹八字段保持，具体规则见 [runtime-integrity.md](runtime-integrity.md)。以上替代历史跳过QA15、双Dockerfile强制和新增运行前证明口径。

一期逐题反馈按当时适用规范和题包版本区分；新版已修复的个别问题，不自动扩成新统一门槛。需要迁移的旧包只反馈与当前验收有关的具体差异，不要求无依据地重跑全部历史作业。
