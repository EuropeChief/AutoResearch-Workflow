# 旧题格式迁移豁免政策

版本：v0.3.10-legacy-waiver.2，2026-10-22。此政策替代此前 gpu-waiver.1 的过窄范围，不与其条件叠加。

## 适用口径与优先级

本轮用户明确授权：指定旧题目前只返修格式和交付配置、不重新运行研究。以新版 v0.3.10 为完整检查框架，另加旧题迁移与新增要求豁免，不回退至旧版，也不把未经运行的新环境描述为已经通过。授权不能来自题包自称、旧报告 PASS 或截图本身。

本文件决定本批最终豁免；其他 reference 和原脚本中的严格硬要求保留用于原判。凡已逐原因获免的新 NOP、八字段、哈希、当前内场记录或新联网防护适配，不再要求专家本轮补跑/补造。新题、未指定批次或不明原因仍用完整标准；政策适用不明先核现有版本材料，不能默认为全部通过。

实际旧要求见 [旧新对照](legacy-standard-comparison.md)：二期 H05/H06 无运行材料可 N/A，未统一强制 NOP；每轮只需 round/method_summary；未统一要求四项 task_binding；QA15 当时跳过平台资源上限核查。不能因为这些在新版是必交就称旧题“原本缺证据”。

## 可处理的原因与对应检查项

| 原因代码 | 检查项 | 本轮具体处理 |
| --- | --- | --- |
| target_gpu_record_gap | G03、QA03、QA13、QA15 | 原硬件正式研究符合原科学要求，换 H20/L20 后没有重新生成成绩、耗时、锚点或比较证据。保留真实卡型和旧结果，不强迫重复研究。 |
| new_standard_validation_dependency | G03、QA03、QA13 | 新平台、新联网场景或新版绑定要求导致原合格研究的当前适用性未验证，可免新增复验；不豁免原数值失败、不公平协议或已确认无效分数。 |
| gpu_candidate_list_compatibility | H02、QA15 | 按最新教程V4，候选列表含其他型号不单独判错，须支持并为内场选用H20/L20；原3.10按列表整体否决的派生原因可按新口径解除。只列其他卡、实际内场选其他卡或CPU加GPU不免。 |
| new_resource_evidence_gap | QA15 | 旧标准未要求的新版资源核对记录/字段欠缺，或格式迁移后目标环境尚未验证。结合现有材料记录推断，不填伪实测。 |
| new_trajectory_schema_gap | QA18、QA21 | 历史轨迹符合当时两字段要求但不符合新版八字段。不强迫补造每轮分数、时间和最佳标记；已有记录仍核实。 |
| new_trajectory_run_metadata_gap | QA18、QA21 | 旧版未要求的最高推理档、同 Prompt/资源、独立空输出等启动级证明欠缺，可免本批补跑或补造；原本真实非独立、缺轨迹或已确认污染不免。 |
| new_task_binding_requirement | QA21 | 旧记录未记录新版四项哈希，或目录/封装/配置迁移后旧绑定不同。核对已有说明和版本关系，不能倒填运行前哈希。 |
| unsupported_network_policy_transition | QA05、H02 | 移除当前不支持的禁网/白名单配置后，联网或外部查表约束尚未落实的新平台适配缺口。允许本轮不新增防护实现或重跑；平台后续验证，未落实不写已生效。 |
| internal_image_preparation_pending | H03、H05 | 已有有效构建交付方案，但尚无内部实际镜像选择/tag/当前内场调用证据，留待字节侧准备；外部作者不负责访问内仓或回填。 |
| new_current_trial_requirement | H05、H06 | 旧标准未强制而无 NOP/Trial 记录，或改包后未重跑当前版本；可使用真实历史材料，不要求其预先拥有新版 NOP/hash。 |

QA17 不接受直接申请，必须按 H01–H06 原子原因覆盖后派生。某个 Harbor 子项实际合格或不适用就保留原判；仍有未覆盖子问题不能一起放行。一个原子原因在 QA 与 H 重复派生时，分别核对关联，不凭同编号或同关键词代填。

## 仍需处理与真实性保护

- 当前格式/配置照常返修：缺核心文件、实际采用方案的构建上下文/COPY/依赖资产/入口错误、无评分实现或提交物移交、Compose、separate/每沙盒单容器、公开 Dev/私有 Hidden 等交付缺陷不免。不强制双 Dockerfile；复用镜像分支按实际调用核对。
- 当前内场实际 GPU 使用 H20/L20；CPU 题不增加 GPU。最新教程允许 gpu_types 中保留其他候选，只要支持并实际选择 H20/L20。不能把缺新卡实测当作已验证，也不能把确定的当前错误资源配置包装成记录缺口。
- 不保留当前不支持的 storage_mb、禁网/白名单字段以声称约束生效。删除字段后的新场景防护欠缺可以豁免本轮适配，但已确证原研究读取 Hidden、查表污染、作弊、造假或评分故障，不能据此变成有效成绩。尚未验证、普通联网或下载依赖，不直接认定作弊。
- 科学要求未因这次豁免取消：原有效方法空间、合理公平 Baseline、全部正式成对结果、真实提升和数值门槛继续检查；旧标准本就要求的两条独立轨迹和有效时长继续核查。旧记录真正缺失/损坏与仅缺新增字段要区分。
- 算法、研究数据/切分、评分含义、指标、seed/预算或协议发生实质改变时，不能用“格式迁移”沿用不对应的旧成绩。并非任意文件字节变化都是实质变更；搬目录、改路径、补封装等由审核人查现有差异及调用关系，不要求只有 gpu_types 可变。
- 不新增统一完整旧快照、当年已记录的哈希、原本没有的 NOP 或审核 JSON 为专家必交件。查现有材料足以判断就使用；不能判断的具体问题保持待核，说明缺口，不编造因果。

## 执行及结果

1. 完整执行主 Skill 的 v0.3.10，只读生成严格 `report.json/md/txt` 和 `return_to_expert.txt`。所有原严格脚本及 Baseline 专项与原上传包逐字节一致。
2. 审核人根据已有标准、原提交/记录及本轮迁移说明，逐项判断原因。请求放题包外；它是审核工作底稿，不是专家新 Schema。工具会验证文件引用和原判绑定，但不替审核人鉴定历史真实性或新旧要求归属。外置 JSON 不是身份认证，不能自动相信作者提供的同形文件。
3. 用 `scripts/legacy_migration_waiver.py` 生成模板，再完成审核底稿并启用指定 profile。工具读取原报告与 review、核对实际题包和原判，再单独生成 `waiver_report.json/md/txt` 与 `waiver_return_to_expert.txt`，不改严格报告或原材料。
4. 每项复合缺口须覆盖全部阻断原因。模板列原子 key、状态和摘要 SHA；有不属于本轮豁免的原因，不能声明全部覆盖。严格原状态、原摘要、证据及剩余整改要求都在结果保留。
5. 有未豁免 fail 则 FAIL；无 fail 但有未覆盖 manual/不完整申请则 INCOMPLETE；其余检查满足且有获准豁免才 PASS_WITH_WAIVERS。原本严格 PASS 不制造豁免；没有启用请求不生成豁免通过。

对于既有人工 review 已直接写为语义 fail 的项目，工具不靠豁免底稿把其真实语义失败抹掉。若质检员重新核对发现该旧判其实只来自本轮新增要求，应保留旧报告，记录更正原因与已有依据，再另目录生成修正审阅后的严格报告并申请豁免；不是要求专家补跑，也不能为了自动通过把真实失败改成 pass。新增字段的可计算失败仍由原脚本保留。材料不能区分时，只将具体申请列审核人待核，不新增专家统一交付义务。

报告必须明确：本次未执行题目/模型/Docker/Harbor；当前目标卡、当前 NOP、联网新防护与内场镜像运行有何仍待平台验证。豁免通过仅是本轮迁移验收结论，不代表完整目标环境验证完成。`audit_collection.py` 仍汇总严格报告，不把本分支的豁免结论冒充普通 PASS。

## CLI 与审核工作底稿

使用可信的 Python 3.11。从 Skill 目录调用；所有输入输出用绝对路径。先有真实完整严格报告与 review；ZIP 的 artifact-root 使用严格 inventory 中安全解包的 root。工具不执行包内代码、不构建镜像、不调用模型。

```bash
python3.11 scripts/audit_task.py /path/to/current.zip \
  --out-dir /path/to/qa/strict --review /path/to/qa/review.json

python3.11 scripts/legacy_migration_waiver.py \
  --report /path/to/qa/strict/report.json \
  --review /path/to/qa/review.json \
  --artifact-root /path/from/strict-inventory/root \
  --out-dir /path/to/qa/legacy-waiver \
  --template-out /path/to/qa/waiver_request.json

# 审核人完成模板中事实核对、逐原因覆盖后再启用；不能原样套模板。
python3.11 scripts/legacy_migration_waiver.py \
  --report /path/to/qa/strict/report.json \
  --review /path/to/qa/review.json \
  --artifact-root /path/from/strict-inventory/root \
  --waiver /path/to/qa/waiver_request.json \
  --out-dir /path/to/qa/legacy-waiver
```

输出和底稿须放题包外，独立于严格输入；不可覆盖输入 JSON。完整工作底稿由 `--template-out` 按真实原报告生成，默认不启用、事实确认默认 false；字段以本版工具 `--help` 和模板为准。profile 固定 `legacy-format-migration-v2`，schema_version=2。绑定严格报告/review 原字节 SHA；当前指纹由工具读取现包核对，不要求专家历史运行具有同一哈希。原子覆盖关联原状态及原摘要 SHA，防止把另一份报告或变更后的发现套入豁免。

`reviewer_context` 记录本轮指定旧批次及仅格式/配置迁移、历史标签保持真实和豁免范围无实质故障；各 request 写原 target/status/summary_sha256、具体 causes、原子 coverage 和保护项核对。事实断言只限被豁免部分，不阻止同题其他真实失败继续保留。只有审核人明确完成这些判断才启用；证据文件存在不等于其内容足以支持判断。

### 按原因补充的审核字段

模板的 `causes` 默认空，不自动选择原因；仅保留本次实际申请的 request，其他问题仍留在原报告。每条 cause 为 `{code,summary,evidence}`；coverage 的 cause 填对应 code，逐个覆盖模板给出的原子 key。不得清空受保护原因来制造“覆盖完整”。

以下是审核工作底稿的字段，不写入专家题包。确认项只有核实后才填 true；`evidence` 继续引用 artifact-root 下已有文件，可带行号或 JSON 定位。

| 原因 | 专用字段 |
| --- | --- |
| unsupported_network_policy_transition | `protected_review.network_change_is_platform_migration_only=true`、`no_confirmed_historical_score_contamination=true`。说明新增平台场景，不要求新防护已落实。 |
| internal_image_preparation_pending | `protected_review.complete_build_materials_present=true`、`platform_internal_image_work_pending=true`。没有 Solver Dockerfile 而采用合法源镜像时，另核 `valid_prebuilt_source_image_present=true`，并填 `source_image_review={source_image,summary,evidence}`，记录实际可复现源镜像与依赖/资产方案；工具不联网验证仓库。 |
| new_current_trial_requirement | `protected_review.current_trial_not_legacy_requirement=true`、`no_confirmed_failed_trial=true`。原无 NOP 可适用；有确证失败不能伪称成功。 |
| new_trajectory_run_metadata_gap | `protected_review.historical_runs_genuinely_independent=true`，另填 `metadata_gaps` 数组，每条含 `requirement`、`state="missing_evidence_only"`、`legacy_required=false`、`summary`、`evidence`。requirement 仅取 `max_reasoning_level_record`、`same_prompt_task_dev_resource_record`、`independent_output_start_record`、`model_runtime_settings_record`；这里指新增证明记录，不免实际非独立或已确认执行条件不公平。 |
| gpu_candidate_list_compatibility | `protected_review.target_selection_is_h20_l20=true`、`no_other_gpu_selected=true`，另填 `gpu_selection_review={selected_gpu_type:"H20"或"L20",summary,evidence}`，依据已有配置/平台选择约定核对本次内场目标；不改历史其他卡型标签，不要求新跑日志。 |

例如，仅缺当前 NOP 的已核实申请，在对应 request 的 causes 记录 `new_current_trial_requirement` 及现有版本说明，逐条覆盖该项模板列出的 H06 原因，再填上述两项 Trial 保护确认；不添加虚构 config/result/reward 文件。若严格报告还存在 H03 缺 COPY 源文件，该问题仍保留并使最终不能通过。
