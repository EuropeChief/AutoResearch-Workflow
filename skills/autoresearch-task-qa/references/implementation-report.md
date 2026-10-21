# 复核输入与报告（schema 6）

review.json 由质检代理逐项读证据后在报告目录创建，不信任提交包同名文件。必填 overview、content_gates、runtime_review、trajectory_review、resource_review、format_review、checks、harbor；risk_notes 可为空。旧 review 缺新门槛不能原样当终稿。

无 --review 的输出标记 review.stage=collection，是文件与数值收集初稿；不得将默认等待项、未整理跑分或未复核 NOP 说成材料缺失。初稿不产生专家整改结论。应用实际语义 review 后 stage=semantic_review，仅真实证据不足保留 manual。

终稿中的 manual 显示为“待补充核验”，说明已复核但证据不足；初稿显示“未完成检查”。轨迹可信性摘要区分内容/行为、评分来源和run_summary哈希的具体缺口；QA15 摘要合并重复作业缺口，完整逐作业明细仍保留在 JSON。

## 共用条目

QA01–QA21 恰好各一次，status 为 pass/fail/manual/not_applicable；仅 QA04/QA19 可不适用，QA15 必查。G01–G03 恰好各一次，不能不适用。H01–H06 恰好各一次；H06 必查，缺少 NOP 记录时为 fail，runtime_status=not_run，QA17 不通过。H05 无可审调用配置时可 not_applicable。已有配置或 Trial 则必须核查，不能选择不适用绕过反证。

每条至少 id/status/summary/evidence。summary具体简短（QA/H≤220字）；evidence为包根相对的真实文件，可带行号或JSON字段。pass必须有证据；确定缺文件可无证据，但要写缺失路径。QA07/08引用只许instruction.md；QA12“清点无.git”允许特殊 @inventory。

仅在引用明确提供行号或 JSON 定位时校验其位置：支持 `file.py:12`、`file.py:12-15`、`file.py#L12`、`file.py#L12-L15`（也可 `#L12-15`），行号从 1 起、范围含两端，不得倒序或越界。JSON 支持 `result.json#/metrics/items/0/score`（JSON Pointer，`~1` 表示 `/`，`~0` 表示 `~`，支持 URL 百分号编码）、`result.json#$.metrics.items[0].score`、`result.json#field=score`，以及 `result.json#score`、既有 `result.json#agent_execution[0]` / `result.json#metrics.score`。点号/方括号字段语法限 ASCII 标识符与非负数组下标，其他键用 Pointer；显式引用的字段必须存在，值为 null 仍算存在。JSON 的单个 ASCII 标识符（如 `#score`）也是明确字段定位。普通说明型 fragment（如 `#说明`、`#score-notes`、`#score explanation`）及 Markdown 等非 JSON 文件的普通锚点不当作强制 JSON 字段。未给定位不强制补，所有形式仍须是包内真实文件且不能越界。一般 evidence、Harbor 及其默认消费者共用定位检查；只验证位置存在，不自动判断语义支持，也不增加 G03 原值与日志的自动比对。明确定位的文本/JSON自动读取上限为 4 MiB，超限须缩小所引证据或人工核对，不假装已完成自动定位。

失败/待补证项另填 remediation 和 acceptance_evidence：前者是专家可执行的修改动作，后者是重交时应提供并可验收的材料说明，均为非空文本。G项还填 reason_code（如 PURE_HYPERPARAMETER_SEARCH、UNDERTRAINED_BASELINE、INSUFFICIENT_GAIN）；不要把通用“请完善”当修复建议。QA17由H子项汇总，修复说明须反映具体H项/路径问题。

## overview

optimization_surface 保留 summary、modifiable字符串数组、fixed字符串数组、metric_and_gate、evidence。

baseline_reference 包含：

- baseline_method、reference_method：两个非空方法介绍，写实际算法、初始化/训练方式及方法差异，不能只有分数。
- metric、direction（minimize/maximize/unknown）。
- paired_runs：全部正式seed的数组，每项 seed、baseline、reference、baseline_valid、reference_valid。数值可为null表示未知，不能编造。seed不重复；有效性为true/false/null。
- baseline_mean、baseline_sample_std、reference_mean、reference_sample_std：来自原始值的统计量；不足两轮则样本标准差为null。均值可负，标准差不可负。
- improvement_summary、quality_gate_summary、evidence。文字必须与原始数值和程序复算一致。

trajectories 恰好两项，各项 name、status（complete/partial/missing/unreadable）、source_path、packaged_rounds、reported_effective_rounds、duration_hours、summary、final_result、evidence。缺轨迹仍保留一项并标missing，不造路径；完整/部分轨迹需真实source_path。duration_hours是实际有效时长，非预算、墙钟跨度或容器uptime；已知时应等于runtime_review对应effective_seconds/3600，未知可为null，不能以较大的墙钟值代填。报告中的有效时长以已复核effective_seconds为准，两个已知值不一致须核清来源后修正；脚本仅容忍 60 秒以内的展示取整差，不改变有效时长门槛。

## content_gates

结构为 schema_version:1 和 checks:[G01,G02,G03]。G01/G02按research-quality.md语义复核；G02可保存dimensions以记录训练充分性、实现、代表性、公平性、选择完整性五维证据。

G03另填assessment：

    {
      "direction": "minimize",
      "formal_seeds": [101, 202, 303],
      "declared_run_count": 3,
      "evaluation_mode": "stochastic",
      "same_protocol": true,
      "quality_valid": true,
      "upper_bound": 0.1,
      "threshold_basis": "当前算法规范：Reference归一化[0.15,0.8]，改善≥3σ_B",
      "absolute_min_improvement": null,
      "absolute_threshold_source": ""
    }

方向/模式无法确认可用unknown，布尔事实未知用null。upper_bound须有可追溯来源，不能为了通过倒推。absolute_min_improvement只在任务预先声明额外阈值时填写，非空值须有来源。确定性任务无统一5%门槛，Baseline均值为0不需要编造除零替代阈值。

程序据paired_runs复算G03.computed：全集/有效性、均值、样本标准差、正向改善、归一化和3σ。明确不达则fail，无法计算则manual；手写pass不能覆盖。数值计算不替代原始result、日志、模型/哈希及协议的语义核验。

## runtime_review（QA16）

必须提供两条轨迹，与overview的name/source_path一一对应：

    {
      "exception_reason": "",
      "exception_eligibility": {
        "non_training": null,
        "short_iterations": null,
        "basis": "",
        "evidence": []
      },
      "trajectories": [
        {
          "name": "Codex + GPT-5.6 Sol",
          "source_path": "expert_evidence/trajectory_codex.json",
          "effective_seconds": 37440,
          "evidence": ["expert_evidence/run_summary.json#agent_execution[0]"],
          "time_accounting": "记录为实际有效时长；排队与安装未计入，依据运行摘要和日志。",
          "effective_method_cycles": 9,
          "next_direction": "尚可验证的合法方向，缺证据时写无法确认。",
          "best_method_revalidated": true,
          "best_method_evidence": ["expert_evidence/专家作业说明文档.md"]
        }
      ]
    }

上例仅展示一个条目，真实输入必须恰好两项。默认两条各≥36000秒。两条各≥25200秒但任一不足10h时，首先要求exception_eligibility.non_training=true且short_iterations=true，basis解释任务不含训练/微调及实际典型单轮耗时，evidence引用源码/协议和耗时记录；随后要求exception_reason、每条≥3个有效方法闭环、具体后续方向、best_method_revalidated=true与复验证据齐全，才通过7h例外。队列/安装/构建故障/阻塞扣除依据要说明；不可把墙钟起止直接当有效时长。涉及训练/微调或迭代不短且任一不足10h时为fail；任何轨迹不足7h为fail；缺实际时长或例外资格证据为manual。两条都达10h时不强制填写例外资格。不得凭“非训练”三个字推定迭代很短，也不新增统一几分钟的阈值。旧observed_runtime_seconds和单条6h规则不再覆盖判定；runtime_candidates仅为收集观察。

## harbor 与 Docker

部署能力按[当前内场部署口径](innerfield-deployment.md)填写harbor.deployment_profile（默认innerfield-maso-v1）与capability_review；generic-harbor须deployment_basis说明实际其他provider，不能称内场合规。字段由质检员归纳已有材料，专家无需新增同名文件。自动检查的harbor.deployment_contract汇总配置与能力反证，映射QA05/H02/H03/QA17；确定不支持配置不能被手填pass覆盖。

容器组织与GPU使用的语义结论记录在既有H03的summary/evidence，说明实际发起方、阶段、调用及执行位置；确认题包要求／允许或实际依赖额外工作环境记fail，关键调用未核实记manual，满足要求时只按静态证据范围记pass。题包符合规则但Agent自行违规则按QA18记录行为及归属，不自动归为作者部署缺陷或判成绩无效。题包部署结论沿H03→QA17汇总，不新增字段或作者材料表。Compose文件扫描未命中不能代替此复核，也不能仅凭Docker/SSH/HTTP等关键词判失败；判定范围及合法行为见innerfield-deployment.md。

harbor 必填 task_root（相对包根）、target_version、provider、version_basis、checks:[H01..H06]，另必填path_contract：

    {
      "profile": "harbor-environment-v1",
      "profile_basis": "目标 Harbor 版本独立 Verifier 规范及本题实际选中的镜像/构建入口"
    }

teaching-task-root-v1与harbor-environment-v1的精确位置由程序计算，按docker-path-contract.md核对。custom另需dockerfile/build_context/runtime_task_root与adapter_evidence包内真实引用。未知动态语法可提交manual_resolution={summary,evidence}进行语义解释；确定源缺失、路径越界、Agent 复制最终私有评测材料或缺实际选中构建的 Dockerfile/入口，不能用人工pass覆盖。允许复用 Solver 镜像或专用 Verifier 镜像/构建；引用实际选择配置和 tests 上传/预置入口。预构建镜像内容及依赖以已有镜像/运行证据复核，不凭镜像名自动通过。

H01/H02 通过需引用选中 task.toml；H03 不能用未知 provider 通过。H06 要求当前题包版本的一次 NOP Trial：核对 config.json 与 result.json 的 Agent 为 nop、reward 与非空日志、任务及版本对应关系、separate 模式、异常/结束状态，确认构建与运行链路可用。版本关联允许配置、日志或专家说明的trial_task_binding；不强制NOP新增四项哈希。仅名称且无版本依据保留manual。缺记录时 H06 fail 且 runtime_status=not_run；其他 Agent Trial 可作补充材料。可复用平台已有同版本 NOP 记录；0 分本身不判失败，Oracle 非必交。

还需填写 `harbor.hidden_review`，而不是检查固定目录名：

```json
{
  "hidden_review": {
    "mode": "prebuilt",
    "summary": "说明私有材料如何进入 Verifier、评分器在哪里读取，以及为何 Agent 不可见。",
    "evidence": ["workspace/harbor_task/tests/Dockerfile", "workspace/harbor_task/tests/grader.py"],
    "asset_paths": ["workspace/harbor_task/tests/private_cases.json"]
  },
  "submission_paths": ["/workspace/solution"]
}
```

路径均为真实包内引用。`mode` 可为 prebuilt/generated/injected；仅 prebuilt 要求实际非空 asset_paths，其他方式须有准备实现、调用入口与安全边界证据，不能只写“平台会注入”。自动脚本校验引用存在，内容与调用语义仍由复核者判断。缺证据保留 manual。

`submission_paths` 指 Verifier 实际需要接收的 Agent 绝对路径，默认 `/workspace/solution`；脚本核对 task.toml 顶层 artifacts 源路径覆盖情况，并认可默认移交的 `/logs/artifacts/`；完全使用该默认目录时无需额外声明。任务采用其他接口应据实填写。`artifact_override={summary,evidence}` 可记录目标版本 Job 覆盖，未获静态解析的覆盖仍 manual；不能用文字覆盖确定缺漏。

历史 Trial 路径与解压路径不同，可用 `trial_task_binding={summary,evidence}` 提供真实任务/版本映射证据；校验信息应来自运行/打包材料，不为通过编造。仅名称一致不证明版本一致，有明确不同任务或校验冲突须解释或退回。任务身份自动核验不鉴定日志真伪。

## format_review

status为aligned/aligned_with_extras/deviations/manual，summary说明语义复核结果，additional_suggestions数组每项path/classification/recommendation。classification为extra_allowed/merge_candidate/misplaced/obsolete_layout。八字段轨迹会根据 overview 中两条 source_path 重新解析，确定缺失/坏 JSON/字段错误影响 QA18/QA21，手填 pass 不能覆盖。额外项与一般布局观察不直接扣错；明确必需证据缺失/实际调用失败映射至对应QA/G/H，等价实现不得因名字不同而失败。

语义复核以等价材料认定 aligned/aligned_with_extras 时，summary 须解释原始观察如何被解决；原观察保留 JSON，不再列为专家整改。空 stdout 不自动证明未重载；应核对同轮独立重载结果、退出状态、质量门及产物关联。trajectory_source_map/index/time_provenance 是附加来源记录，不因文件名含 trajectory 就作为第三条最终八字段轨迹。

## 总评与输出

schema_version=6，policy.revision=innerfield-deployment-v6。保存21项counts、独立gate_counts、Harbor路径结果与review.completed。任一明确内容门/适用QA失败，总评FAIL，即使其他项尚未复核；无失败但有未完成为INCOMPLETE；全部完成且适用项通过才PASS。总评与检查完成度分别显示。

TXT/Markdown顺序：

1. 优化面介绍。
2. Baseline方法、Reference方法与全部正式成对分数，均值/样本标准差/改善/归一化/质量门。
3. 三项内容门结论。
4. 双轨迹迭代概况与格式建议。
5. 总结论、完成度、Harbor静态/运行状态和21行“检查项/是否通过/原因”表。
6. 可直接复制给专家的退回说明：逐问题列事实、证据、原因、修复、验收材料。已确认失败与待补证分开表述，不推测动机。

report.txt与report.md内容相同，report.json保存全部证据与computed；return_to_expert.txt独立保存专家退回说明。通过时可写无需退回，但不能在未完成时这样写。批量汇总必须保留三门和完成度，不接受schema字段缺失的旧PASS。

## 新增报告与 review 字段

report.task_fingerprint 保存 environment/、task.toml、tests/、instruction.md 的固定四项指纹；report.trajectory_review 保存逐轨迹行为覆盖、分数 valid/invalid/unverified、问题分类、影响和绑定；report.resource_review 保存 QA15 实测及需求估算、计时范围、硬件比较和依据。hardware_review所需字段见[内场口径](innerfield-deployment.md)；以affected_formal_runs或affects_formal_scores明确关联受影响正式成绩，不因校准机不同无差别否定全部运行。review.trajectory_review/resource_review 的字段与判定见 [runtime-integrity.md](runtime-integrity.md)。run_summary中的四项hash重算一致即可通过QA21的版本检查；不强制额外启动记录。旧报告 schema 4/5 的 PASS 不自动满足新版内场复核。review.json本身不新增schema号。

报告在双轨迹概况之后增加可信性/绑定与 QA15 资源表。失败和疑点逐项引用具体位置，并分别给专家修复、验收证据；infra bug 不推定作弊。自动观察候选不直接定性。

QA15的estimate与run_summary简化哈希见runtime-integrity.md。QA18仅以content_status汇总所交轨迹内容，QA21单独核对题包哈希；不因同一缺哈希重复退回QA18。QA16/18反馈须引用具体组/轮/区间和最少验收材料，不能要求所有历史日志或额外启动记录。
