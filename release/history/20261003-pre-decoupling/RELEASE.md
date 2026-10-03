# 0.2.0 PCA 版发布记录

2026-09-30：新版规则、八字段、双镜像、阶段门禁与包内证据接口已更新。Harbor 0.23.0 的真实候选移交、独立 Verifier 与可信 reward 已通过；Seed 有界 CPU 预检及原会话恢复通过，生成 Agent 自写八字段记录。Harbor 版本为用户暂定目标，非项目方正式确认。离线与迁移回归的最新数量以 release/acceptance.json 为准。

有限驱动已实现，run/resume 禁用最终评分，显式 finalize 才可移交。GPT 配置 max、Seed 最高有效档 high（本轮只实际调用 Seed）。Seed 短测同一 thread 内有完成分段和后续预算暂停；真实 Harbor 证明移交/独立评分，离线门禁证明不足 10h 不得 finalize。未伪造时长也未调用官方 Hidden。未测 GPU、长上下文或正式 10h/12h；这些按题验收。详见 [升级实施记录](../AutoResearch新流程设计/PCA_IMPLEMENTATION_STATUS.md)。

本版已生成可迁移包，包内完整携带两个项目方 QA Skill，不含 pilot 运行目录、Docker 镜像或凭据。解包后重跑规则检查和全量测试，结果见中央根 `deliverables/autoresearch-workflow-0.2.0-migration-validation.json`。

以下为 **0.1.0 历史记录**，其中“可用于新题”“已通过”仅适用于旧版，不是本次 PCA 结论。原始证据保存在 [历史发布记录](release/history/0.1.0/RELEASE.md)，旧规则锁在 rules/history/0.1.0/。当前源码验收运行后写新版 release/acceptance.json，不能用它代替真实联调。

---

# 0.1.0 历史发布验收

日期：2026-09-27（北京时间）。结论：**W5 第四项完成，通用流程包可用于新题**。
这是工具层验收，不是某道题目已通过质检，也不是任意新环境的长程运行认证。
W0–W5 至此收口；旧流程、旧题状态及宿主已安装 Skill 未改动。

## 验收范围与证据

| 项目 | 结果与方法 | 证据 |
|---|---|---|
| 权威来源与规则映射 | 来源哈希无漂移；50 条规则、38 个 QA 项映射。沿用已接受的 W0 提炼及子条件表，不把哈希检查冒充语义审查 | `rules/manifest.json`、`rules/catalog.json`；中央 `W0_QA_COVERAGE.md` |
| 六阶段及模块合同 | 80 项自动化测试通过，覆盖证据/规则漂移、冻结与回退、实验统计、双轨隔离与恢复、唯一方法复验、组包和独立 QA 绑定 | [机器验收记录](release/acceptance.json)、`tests/` |
| 迁移与独立接续 | 在新的临时根目录，只复制流程源码及规则依赖，不复制旧根配置、密钥、题目数据或 pilot 运行目录；相同 80 项通过；从其他 cwd 初始化空白测试任务，新 CLI 进程正确返回阶段 1 | 同上；[复验程序](tools/release_check.py) |
| 格式与文档 | Python/JSON/TOML 解析、流程内 Markdown 文件链接通过；薄 Skill 标准校验通过 | 同上；`skills/autoresearch-workflow/SKILL.md` |
| 真实模型链路 | 既有 Seed CPU pilot 的预检、真实评测、Agent 自写两轮记录、同一 thread 中断恢复及原始日志哈希复核通过；不足十小时被 W4 正确拒绝 | [联调报告](../AutoResearch新流程设计/W5_SEED_PILOT.md)、本机 `pilots/seed_cpu/runs/trial02/pilot_evidence/verification.json` |
| 本轮权限修复实测 | 新临时 runtime、无网络/无 GPU/无真实凭据：容器与 Codex 两层边界通过；合成登录凭据对可信父进程可读、对 Agent 命令不可读 | [离线 Docker 补测](release/offline_docker_probe.json) |
| 版本与文件范围 | 发布源码及中央依赖逐文件 SHA-256 固定；不纳入动态报告、运行目录、模型凭据、Codex 二进制构建目录 | [源码清单](release/source_manifest.json) |

本次没有发起模型 API、题目训练或独立质检 Skill。两处边界回归测试先失败、修复后通过；离线探针首次因报告目录不存在而在落盘阶段报错，补齐目录创建后重跑通过，不隐去该失败。

## 此次修复

1. 原权限 profile 默认允许读取容器文件，登录型 `/codex/auth.json` 因而可能被 Agent 工具读取。增加该文件的显式 `deny`；可信 Codex 进程仍可认证。API Key 仍由父进程使用，不进入工具环境白名单。
2. 原只读探针对目录使用文件追加打开，可能因“这是目录”而误判只读。现在尝试创建唯一临时子文件，并仅清理自己创建的文件；可写目录会被正确拒绝。
3. Seed profile 测试不再依赖仓库根历史 `config.toml`；固定两份 TOML 是当前配置源，新环境无需复制那份旧配置。
4. pilot `verify.py` 默认只读；首次保存报告需显式 `--write-report`，已有报告禁止覆盖，避免复核时改写原证据。
5. 更新统一入口、部署说明和薄 Skill 的发布状态，保留先前实施记录的历史上下文。

真实模型 pilot 使用修复前运行底座，其原始报告未重写。当前权限修复由新的无模型 Docker 补测证明，不能把二者伪称同一源码版本的模型运行。新准备任务采用新配置，已准备 runtime 不会热更新，不据此拼接或改写旧轨迹。

## 发布适用范围与保留边界

- 工具源码最低使用 Python 3.11（`tomllib`）；本次实测宿主为 Python 3.13.13。支持范围为 Linux + Docker，真实 pilot 锁定 Codex 0.147.0；其他 Codex 版本需对相关接口定向验证。
- Seed 已做真实 API 短链路；GPT 的真实 API/登录服务端、十小时长上下文压缩、GPU 任务与平台 Hidden 尚未由该 pilot 验证。每道题仍需两组各一次实际 Public/Dev 预检，不因工具发布省略。
- 时长测试与短链路不能证明长程无故障；完整双轨各 ≥10h 净有效，真实性与合法性须结合日志审查。
- 本机 pilot 的 AppArmor 例外只适用于已授权 CPU 联调，不是全局默认，也不是其他题目或新机器的授权。
- 科研判断、Baseline 代表性、Reference 充分性、剩余优化空间仍由专家基于真实结果判断；最终 QA 仍由用户在新会话、仅以最终包为边界运行。
- 版本保持 `0.1.0`，本轮仅关闭预发布状态，不改变规则锁/状态 Schema；不提供旧流程迁移。权威原文或接口变更时按来源升级和受影响检查处理。

## 维护者复验

```bash
python3 AutoResearch新流程/tools/release_check.py
python3 AutoResearch新流程/pilots/seed_cpu/verify.py trial02
```

第一条重验并更新工具验收和源码清单，不调用 Docker/模型；第二条只读检查本机保留的 pilot，外部部署未携带运行证据时不必执行。受影响权限需要补测时，可在同等授权下运行 `pilots/seed_cpu/release_probe.py`，它只使用合成凭据和无网络 CPU 容器。

新题**不必重复本页整套发布验收**；按 [部署与开始](DEPLOYMENT.md) 和 [会话入口](START_HERE.md) 进行题目适配及轻量真实预检。

## 2026-09-30 QA v0.3.1 同步修订

规则锁升级到项目方 QA v0.3.1，增加 AR-050 可见性清单规则，保留 0.2.0 状态 schema 以支持显式 task upgrade。旧 QA 口头豁免撤销；报告绑定、收口与额外材料处理已同步。教程真实 Harbor 门禁保持。变更说明与验收边界见 [QA 同步记录](QA_V031_ALIGNMENT.md)。本修订为离线合同/文档同步，不声称重新运行模型、GPU 或平台 Hidden。旧迁移压缩包仍是生成时快照，跨机使用需重新构建迁移包。
