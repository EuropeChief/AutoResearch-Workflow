# 指定旧题的迁移质检

仅用于用户指定、当前只修格式和交付配置的旧批次。适用范围取自用户指定和已有工作记录，不按题号、日期、缺 NOP 或旧 PASS 自动判定。正常新题沿原 QA 路径留证。全流程 GPU／G02 口径及旧题原因边界见[中央规则](../rules/README.md)和[接入口径](../sources/notices/2026-10-23-standard-waivers.md)。

先修格式并自查，再按[官方技能](../skills/autoresearch-task-qa-legacy-waiver/SKILL.md) `v0.3.10-standard-waiver.5`，使用 `audit_standard_with_waivers.py` 审查完整原标准及已有两轨内容。原件、严格结果和历史记录保留，审核底稿与报告放题包外；底稿也须在官方输出目录外，避免覆盖。

质检员按[官方政策](../skills/autoresearch-task-qa-legacy-waiver/references/format-repair-policy.md)填写原标准 `review.json` 和新版 `legacy_review.json`，在 `standard_resolutions` 中逐条关联原发现、已有证据与处置；这些是内部底稿，不是专家新增必交 JSON。官方命令与模板以随包技能及 `--help` 为准。F01–F07、`format_report.*` 或单独 `audit_legacy_task.py` 的输出不能代替完整终审。

生成官方结果后，可通过现有材料入口重新核对：

```bash
python3 cli.py materials legacy-qa-check \
  --package-root /path/to/current-package \
  --report /path/to/qa/standard/report.json \
  --review /path/to/qa-input/review.json \
  --worksheet /path/to/qa-input/legacy_review.json \
  --result /path/to/qa/report.json
```

四份输入依次为新版入口生成的原标准报告、传给官方 `--standard-review` 的底稿、传给官方 `--review` 的完整审阅底稿，以及 `stage=standard_review_with_waivers` 的最终总报告。命令在隔离解释器和包外临时目录中复算官方结果，核对当前包、输入对应、完整组件、发现与豁免明细，不覆盖原报告，不运行题目代码、Docker、Harbor 或模型。它不自动鉴定历史真实性，也不把包外 JSON 当身份认证。

本轮验收满足后，直接打包入口支持这组成对输入：

```bash
python3 cli.py package \
  --package-root /path/to/current-package \
  --qa-report /path/to/qa/standard/report.json \
  --legacy-review /path/to/qa-input/review.json \
  --legacy-worksheet /path/to/qa-input/legacy_review.json \
  --legacy-result /path/to/qa/report.json \
  --output-dir /path/to/attachments
```

三个 `--legacy-*` 参数须同时提供。完整审查完成且复算一致的 `PASS_WITH_WAIVERS` 可交付，保留原严格判定及平台待验证事项，不把原 FAIL 改写为 PASS。新版没有实际豁免时也可能返回该名称，具体豁免只按明细说明。`FAIL` 保留真实问题；`ERROR`／审核未完成阻止作为完成件交付，应回到质检环节处理底稿、输入或读取问题，不能直接判专家题目不合格。

当前格式错误仍需修复，最终完整 ZIP 仍进行现有格式复检。已按官方原因获免的历史时长、字段、绑定或 NOP 缺口不在下游重复补造；不能按“旧题”或 QA 编号整体忽略错误。内部镜像准备、目标卡、当前 Trial/NOP 和新联网防护等未验证事实保留。时长、历史行为、两轨六维可比性及版本边界见中央规则 M07–M09，不因豁免自动安排研究重跑。

已初始化旧版阶段任务若仍使用 `delivery` 入口，可将同一组结果绑定到原交付记录：

```bash
python3 cli.py delivery qa-bind --task-root /path/to/task \
  --package-root /path/to/task/current-package \
  --report /path/to/qa/standard/report.json \
  --legacy-review /path/to/qa-input/review.json \
  --legacy-worksheet /path/to/qa-input/legacy_review.json \
  --legacy-result /path/to/qa/report.json
```

该显式绑定复用同一适配器，不要求先通过普通新题的 `qa-handoff`。第六阶段和旧归档入口复核当前包及这组输入，沿用上述完整终审判断，不重复阻断已获免的历史问题。输入或题包改变后重新复核、绑定。2.1.3 的 `.2` 报告不直接套用新规则；旧记录用原版本复核，需按新口径验收的当前包重新静态审查。已有旧任务不自动初始化或迁移；新使用者直接使用上面的材料／打包入口。

指定旧题在格式自查后用 `materials legacy-qa-check` 核验本轮资格；普通 `materials check` 仍可能列出历史缺口，该输出不额外否决已获免事项，也不改写为通过。项目方格式脚本不检查 NOP、历史时长、指纹或轨迹字段，无须增加格式豁免过滤。已有完整包走旧交付入口时直接用上述 `qa-bind`，不先调用会重复施加普通要求的 `qa-handoff`／`build`，不为历史缺口补造记录。
