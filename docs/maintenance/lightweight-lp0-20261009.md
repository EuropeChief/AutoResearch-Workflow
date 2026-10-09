# LP-0：轻量化改造基线

日期：2026-10-09。范围：建立开发基线、核对来源、定位旧依赖；不实现 LP-1，不启动真实题目或运行验收。本记录供维护者使用，不是新任务的必读材料或额外门禁。

## 1. Git 基线与回退

- 改造前工作树干净；原分支为 `public-release-20261003`。
- 发布基线：`v1.0.0`，提交 `a5e15a60d2eee9be9d96faa3cb767a279be3718e`。
- 本次从该提交创建 `lightweight-skills-20261008`；发布分支和标签不移动。
- 需要使用旧版时，在保存后续改动、确认工作树干净后执行 `git switch public-release-20261003`；不要 reset、强制覆盖或改写历史。新旧真实轨迹不热切运行代码。

## 2. 当前权威来源与许可

以当前教程优先、当前项目方 QA 次之，用户明确且适用的例外单独处理。历史口头 QA 豁免不恢复；默认 QA15 跳过是当前 Skill 的规则，不是沿用旧豁免。

| 来源 | 本次核对版本 | 仓内原件 |
| --- | --- | --- |
| 专家教程 | `PCA-20260929`，双镜像对齐版 | `sources/tutorial/AutoResearch 专家线下标注教程｜PCA 双镜像对齐版.md` |
| 默认任务 QA | `v0.3.2@2026-10-03`，含必需 NOP | `skills/autoresearch-task-qa/` |
| Baseline 审查 | 当前 QA 配套原件；manifest 标注 `qa-g02-route@2026-09-18`，不虚构独立 v0.3.2 版本 | `skills/autoresearch-baseline-quality/` |

完整路径、逐文件版本和 SHA-256 复用 [rules/manifest.json](../../rules/manifest.json)，不另建规则库。该文件本次 SHA-256 为 `dd6cb09fe45eb61d74da3d669ae7a61070773df3eb761ceee8e0a8a60908f1e3`。

核对结果：12 个来源条目均与 manifest 及工作区原件一致；33 个 bundled 文件哈希均匹配；其中两套 QA Skill 的 30 个文件均与工作区 `.codex/skills/` 原件一致。继承原件自身的分项版本，不把未修改的参考文件全部重标为新版本。

分发沿用用户此前明确允许分发的范围，不把该授权描述成上游统一开源许可。辅助 `autoresearch-task-authoring`、`autoresearch-optimization-surface` 的现有 MIT `LICENSE.md` 和署名须保留；这两个 Skill 是可选方法辅助，不是新增权威来源。不对教程、QA 或整个流程擅自添加 MIT 声明。

## 3. 已确认设计的版本锚点

实施依据保留在相邻 `AutoResearch新流程设计/`，不成为运行时依赖。下表哈希为本次实施前文件 SHA-256 前 16 位；计划和讨论随后追加 LP-0 进度，不表示原内容被重新决策。

| 设计文档 | 快照指纹 |
| --- | --- |
| `LIGHTWEIGHT_IMPLEMENTATION_PLAN_20261008.md` | `6eb00b74c714d5d5` |
| `LIGHTWEIGHT_QA_CONSTRAINT_COVERAGE_20261008.md` | `4fce387abfcb39aaf` |
| `LIGHTWEIGHT_FILE_DEPENDENCY_INVENTORY_20261008.md` | `a46b8d9dd2c1ea06` |
| `LIGHTWEIGHT_PACKAGING_INTERFACE_PROPOSAL_20261008.md` | `f30cc57d8e41b8e66` |
| `LIGHTWEIGHT_EXPERIMENT_INTERFACE_PROPOSAL_20261008.md` | `7fd7cf02ec5f169d3` |
| `LIGHTWEIGHT_MATERIALS_INTERFACE_PROPOSAL_20261008.md` | `e81331f528f4c78f` |
| `LIGHTWEIGHT_RUNTIME_REUSE_DISCUSSION_20261008.md` | `6a73b7005f783348` |
| `POST_RELEASE_SIMPLIFICATION_DISCUSSION_20261008.md` | `5637d7e7384c6525` |

后续实现须保留以下已经确认的边界，不再逐题重新审批：

- 一个轻入口、五类能力 Skill、六阶段导航；不再由阶段状态机控制普通操作。必要科学审查和实际证据不因轻量化取消。
- 已审查的 M01–M13 与 C01–C07 要求保留，默认 QA 与严格规范的区别按当前原件处理；Baseline 冻结前复用项目方审查。
- 实验、材料与打包工具独立接收实际输入；不要求 TaskStore、阶段登记、qa_bind 或旧 selection 账本。打包仍需当前提交包对应的完整独立 QA 通过结果。
- Codex 两轨独立、原生可视交互、真实日志和可复算净时长；默认恢复原会话原 Goal。不因静默、训练等待或另一轨故障强停，不设整轨墙钟上限。
- 正式包只放当前正确题目与必要证明材料；独立 QA 后生成三个 ZIP，并在打包目录写七项填表内容。不中途重跑未受影响的科学实验。
- LP-7 内部验收后单独开展 LP-7T 两道已交付题的隔离适配测试，再进入发行；不得以旧基座证据证明新基座已验收，也不自动重做完整研究。

## 4. 已定位的旧依赖与后续拆除位置

下表是改造定位，不是本次已删除清单。通过代码图检索并核读关键实现确认；测试名称用于定向修改，不要求把旧门禁测试原样保留下来。

| 工作项 | 入口、实现及实际耦合 | 对应文档、模板与测试 |
| --- | --- | --- |
| LP-1 | `START_HERE.md` 要求 task check/init、stage record/finish；`cli.py`、`core.py:TaskStore`、`stages.py` 控制状态与登记。新入口改为能力导航，拆除这些通用操作前置。 | `skills/autoresearch-workflow/SKILL.md`、`docs/stages.md`、`docs/interfaces/state.md`；`confirmation`、`stage-finish`、`workflow-policy` 模板；`test_w1_contract.py`、`test_stage_checks.py`、`test_w5_stages.py` |
| LP-2 | `experiments.py:ExperimentBook._load` 先调用 `store.check()`；`experiment_runner.py` 引用旧选优结果，实验执行受账本与规则锁牵连。改为协议、方法、输出及资源参数。 | `docs/interfaces/experiments.md`；`test_w2_contract.py`、`test_experiment_runner.py`、`test_gpu_pilot.py` |
| LP-3 | `w4_evidence.py` 与 `w4_package.py` 把候选材料及组装接到 TaskStore/实验状态；保留 `trajectory.py` 的真实内容、字段校验，拆开 finalize/build/check。 | `docs/interfaces/delivery.md`、`roll-review` 模板；`test_w4_contract.py`、`test_pca_contract.py` |
| LP-4 | `DeliveryPackage.archive` 调 `StageFlow.check("6.5")`，输出依赖内部 delivery 目录及 `qa_review_sha256`；qa_handoff/qa_bind 和阶段取证串联。去这些登记前置，保留报告与当前包对应、三包内容和压缩完整性。 | `qa-review`、`delivery-form` 模板；`test_delivery_archives.py`、`test_delivery_form.py`、`test_qa_contract.py` |
| LP-5 | `runtime.py:Runtime._load` 同时校验 TaskStore、rules_lock、共享 duration_snapshot，并遍历两轨状态；`duration.py`、`task_git.py` 亦引用 TaskStore。拆成本轨配置/运行实例；保留真实保护、日志与时长证据。 | `docs/interfaces/runtime.md`、`duration.md`、`task-git.md`；`runtime`、`duration-assessment` 模板；`test_runtime_tui.py`、`test_runtime_evaluate.py`、`test_w3_contract.py`、`test_op03_duration.py` |
| LP-6–LP-8 | `harbor_runtime.py` 与运行底座接入、正式发布来源清单及测试需随新接口同步；不是删除真实 NOP/候选链路验证。 | `harbor-execution`、`nop-execution` 模板；`test_harbor_runtime.py`、`test_harbor_pilot.py`、`test_design_decoupling.py`、`test_release_contract.py`、`test_release_evidence.py` |

表中 Python 模块均在 `autoresearch_flow/`，模板均为 `templates/*.example.json`（名称不含扩展名时），测试均在 `tests/`。后续删除依赖时同步改正“为旧登记机制而写”的断言，保留科学有效性、私有边界、真实评分和格式的检查。

## 5. LP-0 验收与限制

- 独立分支成立，发布基线可定位；本次仓内变更仅为本维护记录，仓外仅更新设计计划/讨论进度。
- 来源和附带 Skill 原件一致性已核对，维护记录引用路径及 Git diff 空白检查通过。
- 未修改运行代码、真实题目、个人配置、凭据或正在运行的轨迹；未调用模型、GPU、Docker 或质检 Skill。
- 不把来源哈希核对当作程序测试或新版发布验收；旧发布动态证据不自动延续到未来重构版本。
- 下一项为 LP-1；本记录不接入当前启动、任务检查或发布就绪门禁。
