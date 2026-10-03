# AutoResearch 新流程（0.2.0 PCA 版）

状态：0.2.0 PCA 双镜像版已通过合同、真实 Harbor/Seed 有界联调和异路径迁移验收。Harbor 0.23.0 是当前有限适配目标，不是项目方通用版本声明；每题仍须做真实预检和正式轨迹验收。见 [发布状态](RELEASE.md)、[PCA 环境接口](PCA_ENVIRONMENT.md)。

2026-10-03 工作树增量：OP-0/1 政策与 Git、OP-2 可选稳定性、OP-3 有证据的非训练 7h 例外，见 [Git 操作](OP01_POLICY_GIT.md)、[稳定性政策](OP02_STABILITY.md)、[时长政策](OP03_DURATION.md)。默认仍每轨10h，本次不切换 exec_json 运行模式，也未重新发布迁移包；上述已发布验收仅对应原发布快照。

## 入口

运行包与设计资料已按 `2026-10-03.decoupled` 修订分离，部署不再需要设计仓库；中央教程/QA 来源布局不变。详情及旧任务显式升级见 [解耦说明](DECOUPLING.md)。正式新版迁移发布仍归 OP-8，不把预览包称为正式发布。

专家 Agent 从 [START_HERE.md](START_HERE.md) 开始；六阶段操作见 [SIX_STAGES.md](SIX_STAGES.md)，状态登记见 [STAGE_STATE.md](STAGE_STATE.md)。Codex/Pi 可直接读取同一份 [薄 Skill](skills/autoresearch-workflow/SKILL.md)，无需更改旧流程入口。当前只提供流程包内 Skill 源文件，未自动安装到用户宿主配置。

在仓库根目录运行：

```bash
python3 AutoResearch新流程/cli.py --format json version
python3 AutoResearch新流程/cli.py --format json rules check
python3 AutoResearch新流程/cli.py --format json task init --task-root /已存在的题目目录 --task-id example-001 --confirm-init
python3 AutoResearch新流程/cli.py --format json task check --task-root /已存在的题目目录
python3 AutoResearch新流程/cli.py --format json stage status --task-root /已存在的题目目录
python3 AutoResearch新流程/cli.py --format json task upgrade --task-root /已存在的题目目录
```

`task upgrade` 默认只预览；审查差异后才可显式加 `--apply`。所有题目命令都要求 `--task-root`，不会从当前目录推断题目。初始化必须给 `--confirm-init`，且题目目录必须已存在；旧版 `.autoresearch/` 存在时拒绝混用。

## 固定合同

- 中央 `rules/manifest.json` 锁定教程、QA Skill 及其引用方法的路径、版本、优先级、范围和 SHA-256；`rules/catalog.json` 投影 W0 的 50 条规则，覆盖 G01–G03、B01–B08、QA01–QA21、H01–H06 共 38 项。QA15 的跳过口径显式保留；旧 QA 口头豁免已撤销，当前来源为 v0.3.1，见 [同步说明](QA_V031_ALIGNMENT.md)。规则目录不是原件的替代品，争议以锁定的权威原文为准。
- 题目状态位于 `.autoresearch-flow/state.json`，一次性锁住中央来源和每条规则指纹；六个顶层阶段及 27 个子步骤初始化为 `pending`。检查只判断格式、版本和来源哈希，不自动签署科研或质检结论。
- 子步骤保留输入、输出、证据、审查责任、依赖、规则 ID、历史和待后续证据截止阶段。W5 提供 `stage status/template/ref/record/finish/reopen`，通过不可覆盖记录绑定实际证据、W2–W4 检查及专家/用户确认；不直接改状态 JSON。
- `task_config` 包含题目 ID、类型和最小适配入口；`task configure` 在环境验收前登记实际入口文件。适配入口为任务内相对路径的 `command-v1`，程序不代运行任意题目命令。不得把 API Key、登录令牌等秘密写入状态。
- 显式规则升级保留旧锁和变更历史；受影响的已通过阶段及其子步骤标为 `needs_recheck`。仅来源文件哈希改变时，用原有及新规则的来源定位找受影响规则。升级不自动判通过。
- `0.2.0` 只支持同版本规则锁升级，不提供跨版本状态迁移。旧 0.1.0 任务应使用保留的匹配版本，不能手改版本号绕过。

## W2 实验与评分

操作入口为 `experiment lock/extend/start/finish/report/baseline-check/score-check`；字段、命令和边界见 [W2 操作说明](W2_EXPERIMENTS.md)。正式重复、统计、证据绑定由通用程序完成，题目适配负责实际训练与指标，专家负责科研判断和冻结确认。

## W3 Agent 运行底座

模型配置固定在 [codex.toml](model_profiles/codex.toml)、[seed.toml](model_profiles/seed.toml)。见 [W3 操作说明](W3_RUNTIME.md)。配置 harness 后 run/resume 使用 Harbor 且关闭最终 Verifier；专家明确 finalize 后才可移交评分。无 harness 的旧 Docker 后端仍返回 HARBOR_DRIVER_REQUIRED。两条轨迹框架仍是 Codex，专家宿主可为 Codex/Pi。

## W4 证据和交付

统一入口为 `delivery trajectory-finalize/trajectory-review/best-select/best-verify/build/check/archive/qa-handoff/qa-bind`；字段和独立 QA 边界见 [W4 操作说明](W4_DELIVERY.md)。最终轨迹只从 Agent 自写 JSONL 整理；制作日志仅供核对，不代写方法摘要。实际题目方法和平台结论仍须专家/独立质检。

## 验证与边界

```bash
python3 -m unittest discover -s AutoResearch新流程/tests -v
python3 AutoResearch新流程/cli.py --format json rules check
```

这些测试只证明机器合同；真实 Harbor/Seed CPU 短测另有记录，不代表双 10h、GPU 训练、长上下文或独立 QA 通过。实际验收状态见 RELEASE；旧发布证据不得借用为新版通过证明。
