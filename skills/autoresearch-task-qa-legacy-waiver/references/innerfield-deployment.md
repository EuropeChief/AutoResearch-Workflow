# 当前内场部署口径

适用于本批次 MASO / Seed Sandbox，默认 profile 为 `innerfield-maso-v1`。依据为用户 2026-10-12 明确的三条要求，以及[使用 MASO harbor-runner 执行 Harbor Task](https://bytedance.larkoffice.com/docx/MOP9d9m57oMxN1xlBfecbXUtnWe) revision 1627。`storage_mb` 暂不支持来自用户本轮要求；指南另确认禁网/白名单会 warning 后降级联网，以及 Docker Compose 不支持。原生 Harbor 接受某字段，不表示当前内场支持或约束已生效。

明确使用其他 provider 时，可在质检 review 中选择 `generic-harbor` 并引用实际部署依据，按其目标版本做一般兼容性检查；不得据此称“已符合内场要求”。不能为避开内场问题而无依据换 profile。此文件保留原有三类交付要求，并按用户2026-10-15确认补充容器组织与GPU使用规则；不把历史逐题问题或指南其他限制扩成新的统一门槛。

原题开发或历史研究使用其他卡型可以保留真实记录；内场交付前须把题目、镜像及有效配置调整到 H20/L20，并核对换卡对分数、耗时、预算和可复现性的影响。这是允许适配原题，不是允许内场提交其他卡型，也不是只改文档或 gpu_types 就算完成。

## 三条交付要求

| 要求 | 核查与最小修改 |
|---|---|
| GPU 仅 H20 / L20；CPU 题不增加 GPU | 核对 Agent 与 Verifier 各自有效配置及已有记录。GPU 环境使用 `gpus` 与 `gpu_types` 声明数量、允许卡型，例如 `gpus = 1`、`gpu_types = ["H20"]`；CPU 环境保持 `gpus = 0`，无需卡型。资源需求估算仍可依据日志与方法规模推断，不强制每轮型号认证。换卡后保留旧运行的真实卡型，不能只改配置后把旧分数或耗时称为新卡实测；复核或补跑仅限受硬件变化影响的成绩、耗时、预算与可复现性结论。 |
| 当前不支持 `storage_mb`、`no-network` / 网络白名单 | 从有效内场配置移除这些不支持的请求，修正依赖它们的题面与评分约束。warning、忽略字段或降级联网均不算约束生效。删除字段只解决配置兼容，不能证明网络隔离、安全或题目仍成立；依赖禁网的题目须改造为联网条件下仍可成立且由可信侧执行必要约束，或待平台落实后再交。磁盘硬约束也不能只靠已删除的字段，按实际需求核对可执行检查。 |
| 每个 sandbox 必须采用单容器；不部署或调用额外工作环境 | 内场先构建所需镜像并按平台要求填写 `docker_image`，核对真实选中的镜像、入口和依赖。Agent 与 Verifier 分别在当前已分配沙盒内执行，需要 GPU 时直接使用本沙盒的 GPU；不依赖 Compose、额外工作容器或远端GPU工作环境。具体范围与检查方法见下节。仍须显式 `separate`，使用不同 sandbox，Verifier 自带所需依赖，只接收合同允许的提交物。 |

Solver 与 Verifier 可复用同一镜像，也可采用专用 Verifier 镜像。复用环境配置的分支按目标版本上传 tests；显式专用镜像须预置 tests。镜像名或 digest 相同不能代替选择分支与实际隔离核对。CPU Agent 与 GPU Verifier 等组合按各自实际需要核查，不将一侧的 GPU 要求套给另一侧。

## 容器组织与GPU使用要求

本节用于内场交付，限制任务运行依赖的工作环境组织方式；平台自身如何实现沙盒，不由题包中的关键词推定。原有 GPU 卡型、资源和网络规则不变。

1. **每个沙盒使用单容器。** Agent 在平台已分配的沙盒内完成开发、调试和实验。需要 GPU 时，程序直接访问该沙盒已分配的 GPU，不能把另一个沙盒或容器作为训练、推理或调试的工作环境。
2. **任务不承担额外工作环境的部署。** 题面、启动脚本、运行时组件及评分代码不得要求或依赖 Agent、题目自带的调度服务（broker）或其他任务组件申请、创建、启动额外沙盒或工作容器。通过 Docker 命令、Docker SDK 或其他接口启动独立 GPU 工作容器，容器内再运行 Docker（Docker-in-Docker），以及经宿主 Docker 启动并列工作容器（sibling Docker）均不支持。已有的远端 GPU 沙盒或容器也不能作为任务的工作环境；不能仅把“新建”改成“连接已有环境”规避本项。
3. **独立 Verifier 保留。** Agent 和最终 Verifier 仍由平台／评测框架管理并在不同沙盒中运行。两者可以复用镜像；候选按既有 artifacts 契约移交。Verifier 在自己的沙盒内直接计算，不再通过调度服务启动额外工作容器。框架创建这两个沙盒属于正常运行流程，不属于本节禁止的任务自部署；不要求 Verifier 必须在 Agent 开始前创建。
4. **准备镜像和执行本地程序属于不同阶段。** 专家或平台在 Agent 解题前构建、准备镜像及必要依赖是正常准备工作；不能仅因 Dockerfile 或构建示例出现 `docker build` 判失败。当前沙盒内的普通子进程、本地训练或推理进程，以及使用已分配多张 GPU 的本地多进程训练，均不因“多进程”而违规。它们仍须遵守题面允许范围及其他现行约束。
5. **按请求的用途判断外部访问。** 正常的模型服务请求、模型或数据下载、平台通信，不等于把作业交给额外工作环境执行；本节不新增对这些请求的统一禁令，其合法性仍按已有网络、工具和数据规则核对。通过 SSH、HTTP 或 SDK 让另一 GPU 沙盒／容器承担训练、推理或调试，则属于第1、2项限制。不能仅凭协议名、地址或函数名判断用途。

### H03 的检查方法与结论

- 从实际选用的配置、Dockerfile、入口脚本、运行时封装、公开评测入口及最终评分入口出发，沿调用链确认：谁发起调用、处于准备还是任务执行阶段、程序最终在哪个环境运行。调用外部调度服务时，继续核对已有实现或平台说明中实际创建／使用的工作环境；没有 Compose 文件不能据此通过。
- 区分平台／评测框架管理当前 Agent、Verifier 的行为，与题包要求或 Agent 实际执行的额外环境部署。若材料中的部署代码仅供专家在任务外准备当前环境，不能当作 Agent 运行时另起环境的证据；正式运行目录的 Compose 文件禁令仍按下文独立执行。
- 题面或有效运行配置明确要求／允许额外环境部署，或已有实现、运行记录证明题目依赖额外工作环境，H03 记 `fail`，沿原 H03→QA17 汇总。任务要求的申请或启动即使被平台拒绝，也不能使该部署要求符合本节规则。仅因 Docker、broker、SSH、HTTP、GPU worker 等词出现，不能记 `fail`；引用实际调用与用途。
- 题包本身符合规则，但 Agent 自行违背限制申请、启动或使用额外工作环境时，在既有 QA18 轨迹行为审查中记录具体请求、结果及责任归属；被拒绝的请求也须如实记录该违规行为。不能仅凭这类 Agent 行为推定作者的题包存在部署缺陷，也不自动把正式成绩判无效；成绩是否受影响仍按已有证据与规则判断。
- 关键封装、执行位置或部署方无法确认，H03 记 `manual`，说明具体缺哪段调用或已有运行依据；不把未核实写成已违规，也不把静态扫描未命中写成已符合。材料足以支持本节要求且无反证时，可按静态范围记 `pass`，不冒充实际部署、GPU运行或完整隔离验证。
- 结果写入既有 `harbor.checks` 中 H03 的 `summary/evidence`，需要返修时沿用 `remediation/acceptance_evidence`。不新增 QA 编号、报告 schema 或作者必交材料表。当前脚本继续检查原有配置与 Compose 文件规则，并汇总审阅者结论；本版没有新增自动识别任意部署代码的能力。

## QA 与报告

- **QA05**：检查题面依赖的约束是否真正执行。仅配置禁网/白名单、仅收到 warning 或降级联网，不能证明约束生效；确认仍依赖未生效约束则不通过。不得把删配置字段写成安全认证。
- **QA15**：保留完整单轮 ≤2h、GPU ≤8 张 H20/L20、CPU ≤64 核及有依据估算的口径。目标卡型或换卡影响无法确认时只补具体缺口；CPU 题无依据申请 GPU、明确不支持卡型或旧结果冒充新卡实测不通过。硬件变化使正式 B/R 不可比时，同时复核 QA03/QA13/G03 的受影响结果，不能使用无效值证明提升。
- **QA17 / H02–H03**：按内场实际能力检查有效配置与选中构建；`storage_mb`、禁网/白名单请求不可用，不能用一般 Harbor schema 可解析或手写通过覆盖。默认 implementation 交付禁止 Compose（generic-harbor 也不豁免此文件交付规则）：在选定 task 根的 `environment/`（Agent）与 `tests/`（Verifier）直属位置发现 `docker-compose.yaml`、`docker-compose.yml`、`compose.yaml` 或 `compose.yml` 即 fail；与 Dockerfile 并存、预构建镜像、显式 docker_image 或 compose_review.selection=unused 均不豁免。自动扫描只覆盖这两个正式运行目录的直属文件，不递归扫描 docs、examples、history 或其他资料目录；非标准运行入口仍须人工核对，不得据未命中声称没有 Compose。NOP 仍必交，按当前题包与部署配置复核，不新增 NOP 哈希字段。

质检员从现有 task.toml、日志、原始结果和专家说明归纳以下字段；这些是 review 字段，不要求专家新增同名文件或繁琐 Schema：

- `harbor.deployment_profile`：默认 `innerfield-maso-v1`；选择 `generic-harbor` 时填 `deployment_basis={summary,evidence}`。
- 可选 `harbor.compose_review={selection,roles,summary,evidence}`：兼容既有复核字段，`selection`为`unused / selected / unverified`，`roles`列出`agent / verifier`。仅补充非标准入口等语义事实；`selected`在内场仍 fail，`unused`不能覆盖正式运行目录的文件命中。不要求专家新建同名文件。
- `harbor.capability_review={status,summary,evidence,outcome}`：`status` 为 `pass / manual / fail`，`outcome` 为 `effective / not_required / unverified / warning_only / network_fallback`；summary须解释结论，evidence须引用现有材料。缺此复核记manual；当前仍为warning_only或network_fallback时记fail，手写pass不能覆盖。只描述当前交付仍依赖的约束。历史fallback已修复或当前不再依赖时，可据已有证据填写effective/not_required；不能只因日志出现旧warning判失败。
- `resource_review.hardware_review={task_type,score_comparability,summary,evidence}`：`task_type` 为 `cpu / gpu / unknown`；`score_comparability` 为 `same_hardware / revalidated / unverified / reused_without_validation`。`same_hardware` 可说明只有校准机不同、没有把历史值冒充目标新卡成绩。估算仍放在既有 `estimate`，真实测量不改写。硬件问题确实影响正式成绩时，用 `affected_formal_runs` 列出现有正式 B/R result 路径，或设 `affects_formal_scores=true` 并解释；没有这种指向时仅影响 QA15，不自动降级全部正式结果。

自动检查当前配置中的storage_mb、已识别禁网/白名单字段，以及上述两个正式运行目录直属的四种Compose文件名，并结合语义review；自定义封装仍由H02/H03人工复核。分别核对启动environment的基础网络策略与Agent/Verifier执行阶段请求；阶段network_mode="public"不能消除启动阶段的no-network/allowlist请求。普通public/代理配置本身不因网络关键词判违规。ICM镜像及docker_image交付由H02/H03人工核对，本轮不新增“缺docker_image即自动失败”的门槛。结果保存到 `harbor.deployment_contract`：非Compose配置及能力复核汇总至H02，Compose至H03，二者参与QA17；约束类问题另关联QA05。资源与硬件比较参与QA15；仅明确指向且可比性仍为待核/不成立的正式成绩影响QA03/QA13/G03。静态通过仅表示本轮材料范围内满足所查要求，不能宣称镜像已实跑、禁网已实现或所有隔离已验证。只缺具体材料时写待补，并给最小验收材料；不无差别要求历史研究全部重跑。
