# QA v0.3.1 同步说明

此文件仅为历史同步记录，其中旧升级命令与题目路径不适用于当前新任务。当前入口为 [START_HERE.md](START_HERE.md)。

日期：2026-09-30。流程核心版本保持 0.2.0，规则来源修订为 qa-v0.3.1；适用于新流程，不修改历史题目的方法或实验结果。

## 权威与豁免

权威顺序仍是当期专家教程、项目方质检 Skill。用户本次明确撤销先前所有 QA 口头豁免。QA06、QA09、QA10、QA17 均正常检查；QA15 固定跳过来自最新 Skill 本文。QA04/QA19 仅有确定性评估依据时可不适用，H05/H06 依是否存在配置/Trial 材料处理。其他适用项的 fail/manual 必须返修并重新独立质检，不能以 exception/platform_only 关闭。

用户此前“最终无提升不自动失败”的科研轨迹裁定并非 QA 项跳过；仍须真实独立迭代、有效时长和完整记录。当前通用流程继续采用两轨各 10h；不自动启用 7h 特例。

## 同步范围与依据

| 范围 | 当前规则及阶段 | 依据 |
|---|---|---|
| QA06/09/10 | 评分真实写 reward；清理旧结果并原子替换；固定面采用有效只读、恢复或校验。避免附加未要求的全套对抗测试。阶段 2/3/6 | implementation-policy.md QA06/09/10；AR-011/012/032/034 |
| 双镜像与公开 Dev | environment、tests 分别构建；公开 Dev 可用，私有 Hidden 仅独立 Verifier；模型/配置随候选移交。阶段 2–6 | harbor-harness.md H01–H04；AR-004/005/009/033/048/049 |
| Hidden | prebuilt/generated/injected 均可，须有真实准备与调用证据，不能只放空目录或口头称平台注入 | implementation-report.md hidden_review；AR-014/049 |
| NOP/Oracle | NOP 推荐，Oracle 可选；有效候选 Trial 可替代 NOP 作为已有运行证据 | harbor-harness.md 六项复核；AR-033/036 |
| Harbor 两类结论 | H05/H06 无材料可静态不适用、runtime_status=not_run；已有材料不得跳过。教程 L64/L539/L722/L912 另要求真实构建与移交自验，因此流程阶段门禁保留 | 教程优先；AR-009/035/036 |
| Agent 可见性 | workspace 根提供 qa_exposure_manifest.json；真实双镜像摘要、UID、实际视图清单，私有路径不能与可见路径重叠。阶段 2设计/4核验/6交付 | exposure-manifest.md；新增 AR-050，映射 H03/QA17 |
| 轨迹 | 两条各自八字段，Agent 自写、原始指标及真实失败；ATIF 单独识别；有效时间不从时间戳跨度推算 | implementation-policy.md QA16/18/21；现有 AR-038/040/044 |
| 额外文件 | 保留三类目录职责；多交本身不失败，extra_allowed/merge_candidate/misplaced/obsolete_layout 分类，必需证据和调用错误仍要处理 | submission-format.md §3；AR-042 |
| QA 报告 | schema 4、research-quality-v3；QA/G/H 全覆盖，overview、runtime_review、format_alignment、hidden_review 等完整；失败报告可绑定返修，收口须独立完成 PASS | implementation-report.md；AR-045/046 |

原文均锁在 rules/manifest.json，逐规则定位及逆向映射见 rules/catalog.json。QA 输出的格式审阅位于 format_alignment.review（输入 review.json 中叫 format_review）；submission_paths 的输出由 artifact_contract 表示，不错误强制输入输出字段同名。

## 程序与操作

- qa_contract.py 仅验证报告版本、项集、状态一致性及可见性声明引用，不替代独立语义质检。
- delivery qa-handoff 提示准确最终包边界、当前 Skill 版本及无旧豁免；报告必须在包外。
- delivery qa-bind 可接收完整的失败/待补证报告用于返修；6.4/6.5 要求报告 PASS 且 review.completed=true。H06 not_run 的静态 PASS 仍须另过教程动态门禁。
- delivery check 保留必需目录/内容检查，对额外顶层材料给观察；可见性清单据实际镜像填写，不会生成虚假视图证明。
- 现有正式实验、轨迹和旧 QA 报告保留。已有任务运行 task upgrade 预览，审查后 --apply；标记重验不代表自动重跑方法实验。

## 验收与交接

回归测试使用合成夹具；发布检查包含规则来源哈希、本机测试和异路径迁移测试。验收结果见 release/acceptance.json。本次不运行题目的质检 Skill、不消耗模型/GPU/Hidden 预算。

ToB-24 接续时复用有效科研证据，按新锁补双镜像原生动态验收、可见性清单、八字段轨迹与专家材料；原生 Harbor 自验目标仍成立。具体任务状态升级与最终包返修需在题目工作流中登记，本次中央同步不静默改写它。
