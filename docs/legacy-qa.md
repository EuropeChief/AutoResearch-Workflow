# 指定旧题的迁移质检

仅用于用户指定、当前只修格式和交付配置的旧批次。正常新题沿原 QA 路径，版本、指纹、轨迹和必要 NOP 仍照常留存。全流程 GPU／G02 口径及旧题原因边界见[中央规则](../rules/README.md)和[整合通知](../sources/notices/2026-10-22-qa-waivers.md)。

先修格式并自查，再按[官方技能](../skills/autoresearch-task-qa-legacy-waiver/SKILL.md)生成严格报告、review 和官方豁免结果。使用随包官方脚本，不能把当前普通执行修订版报告直接送给官方工具。原件、严格结果和历史记录保留，审核底稿与报告放题包外。

官方命令、默认关闭的模板及逐原因审核字段见[官方政策](../skills/autoresearch-task-qa-legacy-waiver/references/legacy-migration-waiver.md)。审核由已有复核环节基于任务范围和材料完成，不原样勾选模板，不给专家新增一份必交 JSON。官方建议 Python 3.11；流程已在 Python 3.13 验证兼容，不自动安装解释器。

生成官方结果后，可通过现有材料入口重新核对：

```bash
python3 cli.py materials legacy-qa-check \
  --package-root /path/to/current-package \
  --report /path/to/qa/strict/report.json \
  --review /path/to/qa/review.json \
  --worksheet /path/to/qa/waiver_request.json \
  --result /path/to/qa/waiver/waiver_report.json
```

该命令通过隔离解释器调用官方评估逻辑，核对当前包、原判、review 和底稿，再比较豁免结果。只读取材料，不运行题目代码、Docker、Harbor 或模型。它不自动鉴定历史真实性，也不把包外 JSON 当身份认证。

本轮验收满足后，直接打包入口支持这组成对输入：

```bash
python3 cli.py package \
  --package-root /path/to/current-package \
  --qa-report /path/to/qa/strict/report.json \
  --legacy-review /path/to/qa/review.json \
  --legacy-worksheet /path/to/qa/waiver_request.json \
  --legacy-result /path/to/qa/waiver/waiver_report.json \
  --output-dir /path/to/attachments
```

三个 `--legacy-*` 参数须同时提供。交付保留 `PASS_WITH_WAIVERS`、严格原判和平台待验证事项，不把原严格 FAIL 改写为 PASS。只剩适用豁免时可结束本轮专家返修；尚有 FAIL／INCOMPLETE 则继续处理具体问题。正常严格 PASS 无需额外制造豁免。

格式错误仍需修复，最终完整 ZIP 仍进行现有格式复检。内部镜像准备、目标卡、当前 Trial/NOP 和新联网防护等未验证事实保留，不声明“无需任何后续处理”。

已初始化旧版阶段任务若仍使用 `delivery` 入口，可将同一组结果绑定到原交付记录：

```bash
python3 cli.py delivery qa-bind --task-root /path/to/task \
  --package-root /path/to/task/current-package \
  --report /path/to/qa/strict/report.json \
  --legacy-review /path/to/qa/review.json \
  --legacy-worksheet /path/to/qa/waiver_request.json \
  --legacy-result /path/to/qa/waiver/waiver_report.json
```

该显式绑定复用官方严格重建及审核结果，不要求先通过普通新题的 `qa-handoff`。第六阶段和旧归档入口随后复核当前包及这组输入；只有有效 PASS／PASS_WITH_WAIVERS 可交付，FAIL／INCOMPLETE 仍阻断。官方结果覆盖的历史字段和 Trial 缺口不再被旧阶段重复检查。输入或题包改变后重新复核、绑定；旧严格报告和历史运行记录保持不变。已有旧任务不自动初始化或迁移；新使用者直接使用上面的材料／打包入口。

`materials check` 仍按普通材料要求给出缺口；指定旧题在格式自查后使用 `materials legacy-qa-check` 核验本轮迁移结论，不将普通材料检查输出改写为通过，也不要求为已获豁免的缺口补造记录。
