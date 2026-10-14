# 轻量版发行与验证范围

本文件说明共享软件的发行，不给每道题增加发布检查。制作题目从 [START_HERE.md](START_HERE.md) 开始；维护变更读 [MAINTAINING.md](MAINTAINING.md)。当前版本是否完成发布，以 `release/acceptance.json` 的版本、状态和绑定清单为准，不能把历史通过用于当前源码。

## 当前待发布修订：2.1.0+portability.20261014

本修订补充题目可迁移性规则、阶段动作及制作指南，程序版本仍为 2.1.0；规则/包修订身份与当前源码哈希区分本次变更。复用现有预检接口，不新增部署实跑或审批。当前只进行离线合同与静态验证，不将下面 2.1.0 的发布状态、实测或版本专属试用豁免继承为本修订发布通过。当前收据若为 `contracts_passed`，即表示尚未完成正式发布。

## 2.1.0 已发布基线范围

2.1.0 新增六阶段规则视图、题目 Git/三个专家决定的只读预检，以及 Harbor 显式 `artifacts.destination` 检查器修复；不新增最终打包审批，不迁移已完成题目。正式发行以当前 `release/acceptance.json` 的 `status=released`、`release_ready=true` 和绑定源码清单为准。

六阶段合成联调覆盖证据引用、三个模拟决定、阻断/例外、变更失效、制作 Agent 的文件接续、CPU 合成统计及三包压缩；其中科研审查、长轨、授权和 QA 均为夹具，不是真实题目通过。ToB-24 只在独立副本核既有轨迹结构、统计及旧格式差异，不修改原件或重训。

既有单轨/GPU 发布原件已核当前执行源码并可限定复用；2026-10-11 当前源码的原生 CPU 双镜像验收通过，覆盖默认 destination 的 NOP 和显式 `solution` destination 的候选，合计约 93 秒，两者 reward=1.0，未调用模型/GPU或修改宿主安全策略。

用户于 2026-10-11 明确决定本版先不进行独立新会话的全流程试用、可以发布。本版将 `independent_trial` 记为 **waived（用户豁免），不是通过**；未验证全新制作会话仅凭发行入口完成新题流程的易用性和遗漏情况，留待真实题目反馈。此决定仅限 2.1.0，不继承 2.0.0 例外，也不豁免其他三项实际运行证据。短验收不证明正式 7h/10h、真实上下文压缩、科研锚点或具体题包 QA。

## 2.0.0 已有覆盖（历史范围，不等于本版全量实测）

2.0.0 改为五类能力、无状态实验/材料/打包、单轨独立 Codex 底座和显式原生 Harbor 接口。默认运行包不含设计目录、开发测试/夹具、维护记录或旧账本模板；这些仍在 Git 源码仓追溯。旧题使用原版本，不自动迁移状态或热切健康轨迹。

| 已验内容 | 实际范围与限制 |
| --- | --- |
| 工具与迁移 | 全量离线回归、源码仓异路径回归，以及精简运行包的解包、链接/原件哈希/权限与公开 CLI 检查；不依赖设计目录、题目状态或作者鉴权 |
| 单轨运行 | Codex CLI 0.160.0；ToB-17 的 Seed 与 ToB-24 的 GPT 各两次原协议 Public/Dev 训练、原 thread/Goal 暂停恢复与后台作业保留；两轨独立控制和日志/净时长已核。相关修复的当前运行路径由 ToB-24 最新冻结源码证明，不把 ToB-17 较早源码冒称全量最新实测 |
| Harbor 与 GPU | Harbor 0.23.0、Docker Compose 2.39.4；CPU 合成 NOP、有效候选、失败候选的独立 Verifier/artifacts/reward；薄 GPU provider 的实际分配/CUDA 运算和公开 worker 已核。不是所有真实题的完整 GPU Final Trial 或并行训练性能承诺 |
| 环境例外 | 验收仅在各次获准容器中使用限定 AppArmor/seccomp 兼容模式；默认仍是普通策略，不修改宿主、不继承旧许可 |
| 未测/豁免 | 2.0.0 的独立新会话入口试用由用户于 2026-10-10 明确豁免，**不是通过**；实际新题入口易用性留待后续使用反馈。短验收不证明正式 7h/10h、真实上下文压缩、科研锚点或具体题包 QA |

原始训练、会话、配置和授权保留在维护工作侧，不公开鉴权、真实题目或模型。公开收据绑定原件引用/哈希与适用源码。全量开发记录位于源码仓 `docs/maintenance/`；1.0.0 的发布、旧 Codex 0.147.0 和预算监督行为仅从对应 tag/历史记录读取，不作为本版默认说明。

## 维护者怎样发布

以下工具只在**完整源码仓**提供，运行包不要求使用者执行它们。

```bash
python3 tools/release_check.py
python3 tools/build_migration.py --preview --output-dir /明确的预览目录
```

离线检查不启动 Docker、模型或 GPU。它核规则原件、完整回归与干净目录；结果 `contracts_passed`、`release_ready=false`，预览包不能冒称正式包。测试失败应修复或据权威变化说明失效，不能仅为绿色删测。

实际验收完成后，由维护 Agent 以本地证据索引引用已有原件、当时冻结实现和短审阅记录；索引 schema 2 说明见源码仓的 `templates/release-evidence.example.md`，不要求使用者填审批资料。

```bash
python3 tools/release_check.py --release --evidence-manifest /本次证据根/manifest.json
python3 tools/build_migration.py --evidence-manifest /本次证据根/manifest.json --output-dir /明确的新发行目录
```

发布校验读取实际独立轨状态、同 Goal 接续、公开结果、净时长、Agent 自写轨迹、原生 Harbor Trial 与 GPU 分配/计算原件；TUI 观察和许可范围由具名审阅记录支持。源代码、原件和执行标志不符即拒绝复用；只允许 `__init__.py` 中纯版本常量变化，不忽略其他行为/安全变更。版本专属独立试用豁免必须有本次用户明确授权原话和未验范围，不能沿用 1.0.0 许可，其他三项不能豁免。

归档再次核输入、完整文件集合、中文路径、SHA-256 和全部 rwx 权限，运行实际 CLI；不包含 Docker 镜像、运行原件、个人资料或开发测试。`release/history/` 保留被替换收据原字节，但不进入默认包。

源码/证据和归档验收完成后才创建版本 tag；GitHub 同步目标为 [EuropeChief/AutoResearch-Workflow](https://github.com/EuropeChief/AutoResearch-Workflow)，按明确上传授权执行，不 force push、不提交个人配置或运行原件。
