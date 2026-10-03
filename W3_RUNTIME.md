# W3：Agent 运行底座

状态：历史 0.2.0 PCA 发布快照已验证 Harbor 0.23.0 有限适配、候选移交/独立评分及 Seed 同会话有界短测；旧 0.1.0 联调不是新版证据。当前工作树增量未重新做真实模型联调，不借用历史记录宣称已通过。双镜像接口见 [PCA_ENVIRONMENT.md](PCA_ENVIRONMENT.md)，版本及证据范围见 [发布说明](RELEASE.md)。无需设计仓库即可使用本文。

## 范围与分工

专家可以在 Codex 或 Pi 中执行流程；正式双轨迹都由 **Codex CLI** 生成。两组键名为 codex、seed，只读取流程根的 `local/model_profiles/codex.toml` 与 `local/model_profiles/seed.toml`。公开仓库仅提供 [Codex 模板](model_profiles/codex.example.toml) 和 [Seed 模板](model_profiles/seed.example.toml)，不携带作者账号配置，不从当前专家会话猜测或继承。

底座统一负责准备、预检、启动、原会话恢复、日志、计时与错误记录。题目只提供可见文件、Starter、中文迭代 Prompt、固定镜像中的真实 Public/Dev 入口。不要求每题实现 Broker；若评测必须跨权限调用，则在题目镜像适配并预检，不通过关闭保护来绕过。

## 配置与准备

使用 [题目运行模板](templates/runtime.example.json)。所有 path/sha256 引用均指题目根内文件及其完整 SHA-256。模型、推理档位、provider/base_url、上下文与 `auth_ref` 放在上述两份固定 TOML；题目 JSON 不再重复填写 `tracks`。`auth_ref.path` 是当前机器的绝对凭据路径，仅在授权真实运行时读取。不要将密钥值写进 TOML、JSON、Prompt 或命令行。

前期探索不需要账号。到正式迭代准备阶段，创建 `local/model_profiles/`，仅在目标不存在时复制对应示例并填写真实 provider、模型和鉴权引用；已有文件先审阅，不覆盖。`local/` 被 Git 和发行收集器排除，题目提交包也拒绝其中的模型配置。模板里的地址/模型是可修改的样例，不表示服务已接受；用户只需提供其真实配置，不需要改通用程序。

`runtime prepare` 读取两份 TOML，验证后在 `.autoresearch-flow/runtime/config.json` 冻结解析后的参数和鉴权路径引用，manifest 记录原 TOML 路径及哈希，同时生成隔离的 Codex 配置；不复制原 TOML 注释或密钥值。此后修改源 TOML **不会热更新**已有会话，新题准备才采用新值。题目 JSON 中的 `tracks` 被明确拒绝，不再有旁路；缺少当前时长快照也不使用旧版默认值。运行配置变更不能拼接到旧轨迹。

image 必须使用完整 sha256 镜像 ID 或 repo@sha256:digest。镜像需包含：

- 指定版本的 Codex CLI、Python 3、题目训练依赖及事先准备好的 Public/Dev 数据；
- 固定绝对路径的真实评测入口，非 root 可合法调用；只读根文件系统下仍能工作；
- 能透传命令的入口，不强制 root，不在启动时下载数据；
- Codex 受限工作区沙箱所需的运行支持。新生成配置使用 `default_permissions="autoresearch"`：容器文件默认只读，solution/output 和临时目录可写，命令联网关闭；预检显式选同一 profile。嵌套沙箱不可用时预检应失败，不能静默切换成无限权限。

容器只挂载显式 Public 文件、该组 solution/output、该组独立 Codex home 和只读配置。不会挂载题目根、证据仓、参考解、其他组工作区或 Docker socket。镜像内部资产是否正确隔离仍须由题目适配负责，不能只靠文件夹名称证明。

API 凭据支持 JSON 顶层字段（kind=api_key_json、key=字段名）；登录凭据使用 kind=codex_login，省略 base_url/key。登录副本允许刷新，不修改原文件；新生成权限配置显式拒绝 Agent 工具读取 `/codex/auth.json`，可信 Codex 父进程仍可使用它认证。运行目录含鉴权副本与 Codex 持久会话，**不能整体当成最终提交材料上传**。

Seed TOML 保留固定模型/Ark 地址、262144 上下文、160000 压缩阈值和 65536 输出预留；根 config.toml 不动态读取。2026-09-30 配置核对时，GPT 使用 max，Seed 使用最高有效档 high（xhigh/max 对 Seed 映射为 high）；历史依据分别为 OpenAI 的 gpt-5.6-sol 模型文档、火山方舟的 deep-thinking / model-parameter-support 文档，设计仓库记录标识为 `ca978de:PCA_MODEL_CONFIGURATION.md`（仅追溯，不是部署依赖）。`max_output_tokens` 在本工具只检查压缩余量，不声称已设置服务端输出上限。历史 Seed 短测已核对实际 turn_context 的模型和 high；GPT 未在该轮调用。用户自管 provider 的实际接受情况须在新题预检验证，不把配置或原厂能力等同于实际服务已验证。认证路径保持用户原配置，不打印密钥。

`context_window`、`auto_compact_token_limit`、`max_output_tokens` 如填写须同时提供；第三项仅用于预留输出空间的校验，不是发送给 Codex 的请求参数。当前官方 Schema 没有 `model_max_output_tokens`，本工具不生成该字段。`model_context_window` 与压缩阈值按生成的 Codex 配置应用；自定义模型 metadata 仍可能使用回退值，服务端输出限制与长程压缩不在 W5 短联调已证明的范围内，需在实际长程记录中核查。短冒烟不能证明十小时不会遇到上下文问题。


### 仅在确有需要时：显式容器安全适配

Docker 默认策略可能禁止 Codex 内层创建命名空间或挂载。先跑无模型探针定位；
不使用 `--privileged`、`seccomp=unconfined` 或关闭 Codex 沙箱作为自动兜底。
优先使用管理员提供的限定 AppArmor profile；本机 W5 pilot 中，用户明确允许了仅该试验的 AppArmor 例外。

题目配置可选字段如下（只有取得适用授权且审阅过 profile 后才填写；默认没有该字段）：

```json
"docker_security": {
  "apparmor": "经批准的profile名称或unconfined",
  "seccomp": {"path": "runtime-security/seccomp.json", "sha256": "实际完整SHA256"},
  "approval": {"path": "runtime-security/approval.md", "sha256": "实际完整SHA256"}
}
```

prepare 把两份文件复制进运行目录的 `security/` 并锁定哈希，不给 Agent 挂载。
seccomp 要保留 `SCMP_ACT_ERRNO` 默认拒绝；这项语法检查不代替人工安全审阅。
配置不授予 root、SYS_ADMIN 或宿主目录权限。不能将一次 pilot 的许可视作对所有题目的永久授权。
新准备配置共用一个命名权限 profile；已存在运行目录不会热更新，变更需重新预检且不能拼接旧轨迹。

## 统一命令

以下在流程仓库根执行，替换题目目录；题目必须已显式初始化 W1 状态。

```bash
python3 cli.py runtime prepare --task-root /题目目录 --file /题目目录/runtime.json
python3 cli.py runtime check --task-root /题目目录 --track codex
python3 cli.py runtime preflight --task-root /题目目录 --track codex --allow-live
python3 cli.py runtime check --task-root /题目目录 --track seed
python3 cli.py runtime preflight --task-root /题目目录 --track seed --allow-live
```

check 不调用模型。preflight 首先在普通容器和 Codex 内层沙箱分别做无凭据、无网络的边界探针；内层失败返回 SANDBOX_FAILED，尚不会调用模型。两层通过后会真实调用模型及评测，必须事先确认成本；每组各一次，使用独立预检会话与工作区。它要求 Agent 真正执行固定评测命令一次、成功退出、返回有限数值且未改 Starter。不把预检计入正式时长。

runtime 配置 schema 为 2；evaluation.command 是镜像内固定程序 argv，也允许只读 /workspace/public_eval 下的入口，工具生成 /workspace/evaluate。可以传 --candidate /workspace/solution；不能以候选区脚本冒充 grader。smoke_args 仅用于短预检。评测输出可以有进度行，最后一行应为：

```json
{"status":"succeeded","score":0.5,"raw_metric":{"name":"classification_error_percent","direction":"minimize","value":4.5}}
```

上述数字仅说明格式。反馈 score 是归一化值；Agent 写轨迹 score 时必须取 raw_metric.value（示例为 4.5），不能混用。每轮八字段由 Agent 自写 /expert_evidence/trajectory.jsonl，初始与恢复 Prompt 一致。只读 /workspace/starter 与可写 /workspace/solution 分开；输出目录只含本轨新产物，不是完整专家包。

### Harbor 绑定与迭代

新版 `harness` 指定实际 Harness。0.23.0 是用户暂定兼容目标，不是项目方正式版本要求：

```json
"harness": {
  "version": "0.23.0",
  "executable": "/本机独立虚拟环境/bin/harbor",
  "task": "harbor_task"
}
```

`task` 为题目根内相对路径；可选 `docker_config` 指向本机专用 Docker 插件目录。该私有任务目录不挂载给 Agent。prepare 锁定整个任务摘要，镜像/代码/配置改变不得拼接旧轨迹；task.toml 的 Agent 镜像、CPU/内存必须与 runtime 一致。Harbor 启动容器后，有限适配器在该容器内启动非 root Codex，不另起替代容器。GPU 配置仍须在目标机器逐题验证，本轮只验证 CPU。

下面是正式监督接口。无 harness 的旧 Docker 后端继续拒绝正式启动；有 harness 也必须先通过该题的真实预检：

```bash
python3 AutoResearch新流程/cli.py runtime run --task-root /题目目录 --track codex --budget-seconds 43200 --confirm-cost
python3 AutoResearch新流程/cli.py runtime run --task-root /题目目录 --track seed --budget-seconds 43200 --confirm-cost
```

43200 是示例单次墙钟预算，不是新的有效时长要求，也不是金额/token 上限。run 会在预算内自动继续**同一会话**，到各自累计可核活动达到冻结门槛（默认36000秒；启动前获准的非训练例外25200秒）或预算耗尽停止；不要求最终提升。须留出预检/排队/故障开销，不能把最低有效时长直接当作总墙钟预算。7h选择、Prompt生成及防热改规则见 [OP03_DURATION.md](OP03_DURATION.md)。费用仍需用户在服务端设置预算。GPU 索引分别配置，启动前由专家确认空闲。

## 查看与恢复

```bash
python3 AutoResearch新流程/cli.py runtime status --task-root /题目目录 --track codex
python3 AutoResearch新流程/cli.py runtime resume --task-root /题目目录 --track codex --budget-seconds 14400 --confirm-cost
```

首次用 run，已有正式 thread_id 只能 resume。异常时停止后排查，再恢复原会话；没有可恢复会话时报告阻塞，不能伪造同一轨迹。不要删除 Codex home。底座不使用 --last 或临时会话。

run、resume 和 preflight 的 Harbor 作业一律禁用最终 Verifier；不能因预算耗尽或时长达标自动消耗 Hidden 查询。专家确认有效时长、合法迭代、Agent 正常收尾、最终候选已恢复后，才显式执行一次：

```bash
python3 AutoResearch新流程/cli.py runtime finalize --task-root /题目目录 --track seed --confirm-final-score
```

`seed` 仅为示例，应选择经过审查的最终提交轨迹；不是要求两组各查一次 Hidden。该入口要求末段 completed、达到冻结净时长门槛、八字段记录有效、best_method 代码已恢复；先进行合法 Public/Dev 复测，再由 Harbor 移交到独立 Verifier。失败或非有限 reward 返回 blocked，不把 Harbor CLI 的 exit=0 当成功。申请写入 `final_attempt.json`，禁止同轨静默重复评分或看过最终结果后继续迭代。基础设施失败也不自动清账重试，需专家核对是否已消费查询并取得适用授权。此账本是本地防误触，不代替项目方全局查询预算。

若监督进程遭强杀留下 active 状态，先执行 runtime recover --task-root /题目目录 --track codex，再 resume。recover 只停止记录中的专属容器，按最后可核事件收口，不把宕机尾部推算成有效时间。配置、镜像、可见合同变更不会静默接续原记录。

## 记录在哪里、能记录什么

题目 .autoresearch-flow/runtime/ 下：

| 路径 | 内容 |
|---|---|
| manifest.json、config.json | 规则锁、镜像与非秘密配置、可见输入哈希 |
| codex/ 或 seed/ 下 state.json | 正式会话 ID、预检状态、运行片段、扣时与活动状态 |
| 各组 logs/片段ID/codex.jsonl | Codex 实际输出的消息、命令、文件修改、工具结果、使用量等事件 |
| 同目录 stderr.log、events.jsonl | 标准错误及监督进程加时间戳的事件 |
| 同目录 summary.json | 退出状态、片段计时、日志哈希 |
| 各组 harbor/作业ID/ | Harness 配置、console、实际 trial/result.json 与 launch_result.json；最终申请另有 final_attempt.json |
| 各组 formal/solution、output | 方法工作区；Agent 自行写入 `output/trajectory.jsonl` 与当前最佳 `output/best_method/` |
| 各组 formal/codex_home | 恢复所需持久会话及可能存在的鉴权副本，不整体提交 |

可用 tail -f 查看对应日志，不依赖 Agent 自报状态。正式初始 Prompt 必须要求 Agent 每轮写入该组 `output/trajectory.jsonl`，并更新当前最佳 `output/best_method/`；续跑 Prompt 会提醒这两个动作。日志记录 CLI 实际暴露的内容，不承诺内部完整推理、上游已截断输出或独立后台进程全部日志；长训练应同步等待结果，或通过题目评测入口保存并返回可定位日志。W4 从 Agent 写出的 `trajectory.jsonl` 整理最终轨迹；监督日志只用于核验操作和结论，不能替代缺失的 Agent 轨迹。

记录器对已知凭据值、常见凭据字段和 Bearer 文本脱敏；不宣称能识别任意编码后的秘密。持久 Codex home 不属于脱敏日志。达到日志上限会暂停并保留已记录部分，不能当作完整正常运行。

## 计时解释

启动等待、两次进程之间、预检、明确 API 错误之后的停滞不计；无工具运行依据的长静默列为未核实。已观察到工具运行的间隔可计，但不表示空转、重复无变化评测也合法。监督进程丢失时不推算最后事件之后的时间。

status 的 effective_seconds_before_content_review 是**待内容审查的活动时间**，达到冻结的10h/合格7h门槛不自动判轨迹通过。专家仍需查独立性、真实方法迭代、合法操作与完整记录。发现额外无效区间，用 runtime exclude --task-root /题目目录 --track codex --file /题目目录/exclusion.json 追加：

```json
{"start":1790000000,"end":1790000100,"reason":"示例：已证实的外部中断","evidence":[{"path":"证据文件","sha256":"完整SHA256"}]}
```

start/end 为 Unix 秒；重叠扣时只扣一次，原始日志不改写。最终有效性、两组完成门禁和提交格式由后续 W4 消费这些证据。

## 验收

最新离线及异路径迁移测试数以 [验收记录](release/acceptance.json) 为准。覆盖独立目录、API 秘密脱敏、实际工具结果检查、预检不计时、原会话恢复、新会话拒绝、异常扣时、宕机收口、证据漂移、Harbor 资源绑定与最终评分门禁；不调用 Docker/GPU/模型。

新版 CPU pilot 使用授权 Seed 凭据执行真实 Harbor/API 预检和原会话恢复，生成一条 Agent 自写八字段记录。预算暂停时已进入下一轮，当前候选未等于最佳备份，按暂停保留而不伪造最终收尾。GPT、GPU、长上下文、十小时与十二小时未在本轮测试；具体题目预检不能省略。AppArmor 例外仅限本次 CPU pilot，不迁移到正式题目。

Codex 接口依据：[非交互运行](https://developers.openai.com/codex/noninteractive/)、[官方配置 Schema](https://developers.openai.com/codex/config-schema.json)；本次另核本机 0.147.0 的 exec/resume help。
