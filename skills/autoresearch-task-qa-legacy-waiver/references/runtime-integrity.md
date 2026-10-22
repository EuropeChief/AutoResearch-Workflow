# 轨迹可信性、资源估算与题包哈希

## 四项哈希仅记录在 run_summary（QA21）

范围固定为 harbor_task 的 environment/、task.toml、tests/、instruction.md。目录递归包含隐藏文件及空目录；按路径排序，记录路径/类型/文件SHA-256，再对规范JSON求SHA-256，算法为 harbor-task-inputs-v1。mtime、权限、ZIP元数据不参与；四项范围外的 Reference、模型及输出不参与，四项目录内的任何文件仍全量计入，不能自动排除。拒绝符号链接/特殊文件。

用 `python3.11 scripts/task_fingerprint.py /path/to/harbor_task` 计算，复制两个字段到 run_summary.json：

```json
{
  "task_binding": {
    "hash_profile": "harbor-task-inputs-v1",
    "task_content_sha256": "<四项内容指纹>"
  }
}
```

默认适用于本摘要的两条研究轨迹；各轨可在 agent_execution 条目中分别记录这两个 task_binding 字段。若提供agent_execution，它必须是对象数组；损坏的结构不能丢弃后仅凭公共task_binding通过。版本发生变化时保留对应题包并说明受影响运行，另行复核；当前自动检查只与本次选定题包比较，分别记录不代表不同版本已通过验收。旧版较详细绑定仍可读取；run_id、start_record、trajectory_path、trajectory_sha256 均非必填，显式提供的轨迹路径/哈希有冲突时不能忽略。QA重算四项指纹：一致通过，缺字段待补，不一致失败。不要替专家修改题包或伪造历史版本；有版本变化则说明并交相应题包/重做受影响研究。

H06使用已有配置、日志或专家版本说明关联NOP，不强制这两个新字段；QA18审查轨迹内容。不要因run_summary缺哈希重复降级QA17/QA18。

## QA18：审实际提供的材料

### 两组 Agent 与启动条件

两组模型组合可以按实际需要调整；**Codex + GPT-5.6 Sol**、**Codex + Seed 2.1 Turbo** 仅为示例，不是验收白名单。推理档位默认采用所选模型支持的最高档位，记录实际设置及必要说明。核对两组使用同一 Prompt、任务版本、Public/Dev 评分口径和资源配置，各自从独立空输出目录开始；不得把已汇总专家材料、另一组轨迹或最佳解提供给当前 Agent。实际模型、runtime 和推理档位依已有启动配置、run_summary、日志或专家说明交叉核对，不能只按文件名判断。

上述实际配置与启动条件归 **QA18 人工核对**；QA16 继续只处理有效时长及例外。不因模型名称不同于示例、或没有任务卡批准换模型而降级；材料不足以确认实际运行时记 manual 并只补具体说明。确实缺轨迹、未独立运行或记录与实际配置矛盾时按相应问题判定。此项不新增每轮轨迹字段、强制 sessions 或一套新日志，使用已有材料即可。

只交轨迹就审两条轨迹的方法、状态、分数、失败原因和最佳标记；交sessions则一起审。没有sessions不单独退回，也不宣称证明了所有网络行为。报告写清审查范围：例如“已审轮次与最终代码，未提供工具调用”。已交但不可读/删参的调用，仅对实际影响判断的具体缺口给反馈，不要求所有旧包新增全套日志。

关注实际网络/GitHub/论文代码检索、私有Hidden/Reference读取、评分器或reward篡改；结合题面权限、参数/返回与使用方式判断。正常依赖下载、hidden_dim变量和明确排除私有目录的搜索不直接判违规。分数与已交反馈、映射/日志、正式B/R及最终复验交叉核对；不强制每个旧轮次都有独立原始RPC记录。

每轨 review 包含 source_path、score_status=valid/invalid/unverified、summary、evidence、reviewed_sources、behavior_review/score_review={status,summary,evidence} 和 findings。提供的sources均须审或给unrelated_sources解释，不忽略不利sessions。binding_review可保留，但QA18判定独立于QA21的哈希字段。报告content_status是所交轨迹内容结论，score_status还考虑题包哈希是否对应。

finding分类 leakage/cheating/infra_bug/suspicious/allowed；certainty=confirmed/suspected；记录summary、evidence、affected_rounds、score_effect=invalid/unverified/none及具体整改/验收。infra stage为grader/hidden_assets/download/sandbox_start/artifact_upload。已修复且没有分数、也不影响最终结果的infra_bug可记score_effect=none，保留说明而不要求重跑成功研究。confirmed leakage/cheating须记invalid，不能用none抹去真实泄漏或作弊；仅尝试访问且已被阻止、没有获取私有内容时，应按实际证据记allowed或suspicious并解释，不能先定性为已发生泄漏。影响正式B/R时用affected_formal_runs列原result路径，同时退回QA03/QA13/G03。

反馈必须区分：明确违规、影响有效分数的待查问题、已修复故障、材料范围限制。只对当前仍影响结论的问题要求补材料；写明哪组/哪轮、现有证据、具体动作及如何验收。不能泛写“补齐完整行为和运行前证明”。

### 自动观察如何闭环

收集初稿的`report.trajectory_review.sources[].candidates[]`只是待审观察。读完整调用、返回结果及题面权限后，用finding的`candidate_ids`原样引用该观察的`id`；一个finding可解释多个相关ID。正常下载等合法行为也用`classification=allowed`、`score_effect=none`及具体依据消除疑点。只写总结、不给ID，不能解除该自动观察；已审来源中仍有未对应观察时，行为结论保留manual。不要把命中本身改写成违规。没有候选观察时findings可为空，未提供sessions不要求补造。

以下为`review.trajectory_review`的结构示例，仅展示一条轨迹；实际按overview中的两条source_path分别填写，路径、轮次及ID均替换为真实材料：

```json
{
  "trajectories": [{
    "source_path": "expert_evidence/trajectory_codex.json",
    "score_status": "valid",
    "summary": "已核对所交轮次、评分来源和最佳候选；该下载符合公开依赖策略。",
    "evidence": ["expert_evidence/trajectory_codex.json"],
    "reviewed_sources": ["expert_evidence/trajectory_codex.json", "expert_evidence/session_codex.jsonl"],
    "behavior_review": {
      "status": "pass",
      "summary": "第2轮只下载题面允许的公开依赖，返回内容未包含私有材料。",
      "evidence": ["expert_evidence/session_codex.jsonl:12"]
    },
    "score_review": {
      "status": "pass",
      "summary": "成功分数、失败状态和最终最佳方法与已交评分记录对应。",
      "evidence": ["expert_evidence/trajectory_codex.json"]
    },
    "findings": [{
      "classification": "allowed",
      "certainty": "confirmed",
      "summary": "题面允许的公开依赖下载。",
      "evidence": ["expert_evidence/session_codex.jsonl:12"],
      "affected_rounds": [2],
      "score_effect": "none",
      "candidate_ids": ["<从sources[].candidates[].id原样复制>"]
    }]
  }],
  "unrelated_sources": []
}
```

等价命名且未被自动发现的已交工具记录，可在根级`additional_sources`路径数组中补入；无需专家改名。已交但无关的来源用`unrelated_sources=[{path,summary,evidence}]`说明排除理由。已提供的删参/节选sessions确有影响判断的缺口时，`behavior_review.equivalent_evidence`可引用补足该缺口的既有等效记录；不能凭一句“无关”忽略不利调用。上述字段由质检员填写，不新增专家必交文件。

## QA15：有依据的资源估算即可

上限仍为完整一轮评分≤7200秒、≤8张H20/L20 GPU、≤64核CPU。当前内场仅支持H20/L20；CPU题保持GPU=0、不增加GPU且不要求型号。Agent与Verifier按各自有效配置核对，部署支持与换卡规则见[当前内场部署口径](innerfield-deployment.md)。结合正式B/R日志、研究轨迹、Reference/Baseline代码、数据规模和配置，给代表性资源需求估算；有来源、合理且符合上限即可通过，不要求每轮实际配额/型号认证或cgroup/provider生效证明。部署限制实现仍可在QA05说明，不能作为QA15新增强制证据。

区分实测与推断：完整一轮涵盖协议要求的训练/重载/评分阶段；整条10h研究、排队/安装不作为单轮。可用最慢成功运行、训练步数、显存/数据规模及线程配置估算，保留合理余量。旧日志缺单项不阻断整体有依据的估算。H20/L20为目标部署配置，未测过该型号须注明推断，不能声称认证了型号或最低配置。校准机型号与目标资源需求分开；从其他卡型迁移时，旧日志保留真实卡型，不能只改配置或汇总就称新卡实测。仅补受影响成绩、耗时或预算的复核依据/代表性运行，不要求所有历史研究重跑。明确超限或与日志矛盾不能手填通过。

review.resource_review使用status/summary/evidence、estimate与hardware_review；后者由质检员从已有配置、日志和说明归纳task_type、score_comparability、summary、evidence，枚举及判定见[内场部署口径](innerfield-deployment.md)。发现硬件变化影响正式B/R时，以affected_formal_runs或affects_formal_scores明确指向；仅校准机不同而未冒充目标成绩，不自动使正式分数无效。原runs及enforcement_review可作附加材料，不强制逐轮覆盖。

若已提供的完整评分runs与estimate在GPU、CPU或耗时上矛盾，不能用较小估算覆盖实测记录。质检员仅在需要解释差异时，可填`estimate.observation_reconciliation={summary,evidence}`，引用已有材料说明哪些是历史校准、哪些是当前完整单轮需求及换算依据；这不是新增专家必交文件。无法解释的矛盾至少manual，明确当前超限仍fail；历史校准机不同且有充分关联依据时，不因此要求全部研究重跑。

```json
{
  "status": "pass",
  "summary": "基于已有日志和方法规模的资源估算符合上限。",
  "evidence": ["optimization_evidence/baseline_runs/seed_1/result.json"],
  "estimate": {
    "score_seconds": 600,
    "gpu_count": 1,
    "gpu_type": "H20/L20",
    "cpu_cores": 4,
    "basis": "示例：最慢代表运行约100秒，模型与数据较小；留余量估算10分钟。这是估算，非目标卡实测。",
    "time_accounting": "覆盖单轮必需训练、独立重载及评分，不含排队。",
    "evidence": ["optimization_evidence/baseline_runs/seed_1/result.json"]
  }
}
```

上例仅示范estimate结构；完整review还须据真实材料填写hardware_review。示例数值不套用到实际题包。未知的原始测量仍用null；估算字段与来源放estimate，不改原测量。没有足够依据时才manual，并具体指出缺耗时、GPU数、CPU数还是阶段范围。专家可在已有说明补一段资源估算并引用现有日志；仅确实无法推断时补一轮代表性运行摘要，不要求所有历史作业重跑。

## QA16：时长反馈写清具体缺口

默认两轨各≥10h有效研究；无训练且迭代很短的任务可按既定7h例外。现有起止、扣除区间及轨迹时间相互一致即可复核，不强制独立timer、完整CLI或全部RPC原件。扣除排队/安装/明确故障/API失联与行政收集，正常训练与分析可计，重叠只计一次；最终复验另列。

仅预算、孤立时长数字或明显矛盾不能通过。待补时指出Sol还是Seed、哪段起止/扣除不明或有效时长不足，要求补起止/扣除/理由/有效秒数表及相关片段即可；实际不足再继续研究，不能无差别要求两轨全重跑。
