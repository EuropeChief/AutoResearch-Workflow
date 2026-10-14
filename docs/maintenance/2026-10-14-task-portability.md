# 变更：在协议冻结前审查题目可迁移性

## 来源

- 基线：v2.1.0，提交 `ef293dcc24e9c43b268f01d79b54daa9f90961cf`。本次为规则/包修订 `2.1.0+portability.20261014`，程序版本不变；当前规则身份由预检对矩阵、规则正文和 manifest 的摘要确定。
- 2026-10-14 用户确认可迁移性讨论 Q1–Q8，并要求按实施计划开始优化。原话包括“接受，同时，这一点应当在冻结协议前就进行评估”及“当前先根据质检skill中的相关要求进行静态检查与验证即可”。完整讨论和计划保留在相邻设计仓的 `TASK_PORTABILITY_DISCUSSION_20261014.md`、`TASK_PORTABILITY_IMPLEMENTATION_PLAN_20261014.md`；它们不是运行包依赖。
- 案例来源为工作区 `reports/auto1536v3/report.md`、`reports/auto2775/report.md` 及修复后 `reports/auto2775v2/report.md`：分别指出评分端固定 UUID 与入口冲突、镜像/设备/provider 部署证据不足，以及后续修复材料。只有报告，没有完整题包，本次未独立复现其运行故障。
- QA 仍为锁定的 v0.3.2 原件。新增标准以 `catalog.json` 的 U-20261014-01 登记为用户制作约定，不修改项目方原文。

## 影响与不影响

标准补入 M03/M04/M11/C05/C06；调整 M03-S1、C05-S2、C06-S2、M03-S3、M04-S3 动作与派生视图；研究、实现、实验、交付指南引用对应规则。已有研究笔记与预检输入承载审查，Harbor 指南补调用链审阅方法。

保留 6 阶段、44 个 obligation、3 个专家决定，未新增证据角色、CLI、预检 schema、Python 运行实现或扫描器。当前版本 NOP、正式实验、资产隔离和独立 QA 要求保留；旧任务沿用原版本，不热切或改历史。没有新增迁移实跑、逐阶段报告、审批、模型费用或部署服务。

## 修改与退出

差异以本记录所在 Git 变更为准。完整标准只在 `rules/README.md` 定义；复用 mixed 审查、bindings 及定向变更提示，派生视图由原工具生成。纠正 M03-S3 在共同冻结前写“按冻结协议”的时点歧义，改为“按拟冻结的共同协议”。catalog 新增一条约定并同步 manifest 哈希，QA/教程来源字节不变。

默认入口和发布说明标明待发布修订，不沿用基线的 `released` 或试用豁免。新增文件仅此维护记录，不随每题运行包分发。未修改预检示例 JSON，因为现有字段已足够。

## 验证与证据

已运行 `tools/build_stage_views.py --check`，通过。定向执行 `python3 -m unittest discover -s tests -p '<suite>'`：`test_stage_rules.py` 7、`test_p2_preflight.py` 22、`test_p3_stage_gates.py` 18、`test_p4_workflow_integration.py` 2、`test_public_rules.py` 6、`test_lightweight_navigation.py` 5、`test_qa_contract.py` 8，共 68 项通过。

按实施计划做静态场景走读（规则覆盖审阅，不是原题复现或自动探测能力测试）：

| 场景 | 当前规则/接口处理 |
| --- | --- |
| 入口允许新 UUID，worker 固定旧设备 | C06 沿实际调用链识别冲突，review 为 BLOCKED；同机 NOP 不冲销冲突。 |
| 本地 image ID 或缺 provider 获取说明 | C05/C06 区分缺证据与确定冲突；单纯字面匹配不判失败。 |
| 可取得的镜像源构建、组件与资产材料齐全 | 可给覆盖范围内静态结论，不能据此声称动态部署或整包 QA 通过。 |
| 小资产随包、大资产外部固定供给 | C05 同时支持，M11 保留逐 seed 产物、日志和重载证据；缺取得/校验依据待补，静默替换不通过。 |
| 历史绝对路径/UUID、容器 cuda:0 | 按实际语义区分历史记录和当前强绑定，不改写原件。 |
| 延迟指标的环境变化与 B/R/U 适用性 | M03/M04 在冻结前审阅；不自动改相对指标或全量重训。 |
| 已审部署源码变化 | Agent 核实际来源，更新受影响 review/bindings；预检不宣称自动追踪报告中的全部文件。 |
| 缺当前题包版本 NOP | 原 M07/H06 要求继续适用，静态通过不能豁免。 |

`python3 tools/release_check.py` 于 2026-10-14 完成：原目录 557 项、干净迁移目录 557 项测试均通过；192 处链接、143 个运行载荷文件、原件哈希、公开 CLI 与私有/开发文件排除通过。结果见 [当前收据](../../release/acceptance.json)和[绑定源码清单](../../release/source_manifest.json)，状态 `contracts_passed`、`release_ready=false`。旧收据原字节保存在 `release/history/4258f563ecbe2213-7d4cd65feb92f3e7/`。

公开 CLI 在空临时题目执行 `preflight --stage 3 --before anchor_freeze`，确认选择 C05-S2/C06-S2 等前置义务，缺证据返回 2、`ready=false` 且没有写入题目文件。本修订的 `rule_version` 为 `6b8c4114772db708c07719211c5c40ca027108ed7882f2d16947f318230551b2`。对比基线确认全部 obligation 接口（动作说明除外）、阶段定义及锁定 QA/教程字节未变，catalog 新哈希一致。以上为工具合同与静态审查覆盖，不是真实题包或科学验收。

## 待确认与限制

本次修改是制作规则与审查指引，程序测试验证记录、绑定和阶段选择机制，不证明 Agent 必然发现所有设备/环境耦合；真实判断仍须责任人阅读调用链和证据。没有新增语义自动检测器，也不以模拟结论冒充真实 QA。

未运行 Docker/GPU/模型、迁移部署、真实题包 QA 或独立新会话试用；未制作正式发行、tag 或上传。本次完成范围为实施与离线验证，正式发布另按 RELEASE.md 的证据要求处理，历史豁免不继承。
