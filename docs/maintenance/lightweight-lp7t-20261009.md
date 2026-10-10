# LP-7T 真实题适配验收收口

收口日期：2026-10-10。结论：**两题真实运行功能验收完成，可以进入 LP-8 发布准备**；不是正式发行通过，也不是两题重新通过科学标定或最终 QA。

本记录是开发侧唯一汇总。历史提交包、科学协议、正式轨迹及验收原件未改写；本地配置、鉴权、模型和原始日志不进入公开源码或发行附件。开发协调器保留原来的 `completed_awaiting_content_review` 状态，本次完成其后的内容核对，不倒改自动报告。

## 1. 来源、版本与适用范围

| 运行 | 原题来源与原协议 | 实际冻结版本 |
| --- | --- | --- |
| ToB-17 / Seed / GPU 6 | `ToB-17/submission_root` 最终 Adam-family 题面；100 epochs、35,200 steps、45k/5k、batch 128、FP32 | 生产源码对应 `229e6e6`；实现 SHA `184190af248dab87bca43c776e535092be8a044edf162738f67d6d3bf2fa60e1` |
| ToB-24 / GPT / GPU 4 | `ToB-24/submission_pca_h03fix_r1`；60,000 steps、batch 16、BF16、公共 seed 20260912、全 Dev float64 NLL、新进程重载 checkpoint | `8a3ef24`；实现 SHA `36942bdecc9163a554f4a336a4f2ffb863f25daf407d9d556184781a608b33d1` |
| ToB-24 / Seed CPU 伴随 | 原公开 CPU 合同；不训练、不评分、不使用 GPU | 与上述 GPT r3 同一实现 SHA，独立配置、会话和运行目录 |

来源分别按此前独立 PASS 的核心文件定位；原报告只证明原提交边界，不证明新基座。收口时重新校验 `source_binding.json`：ToB-17 的 12/12、ToB-24 的 20/20 个绑定输入大小和 SHA 均一致。两套冻结实现各 57 个文件与快照一致，其中 55 个非缓存源码文件分别与上述 Git 提交一致。

两题来自同一共享代码库，**不是相同冻结版本的两次运行**。后续变化限于 `runtime_controller.py`、`runtime_jobs.py`、`runtime_profiles.py`、`runtime_rpc.py` 中的保护目录和原生显示兼容；最新版本由 ToB-24 GPT/Seed 实测及修复回归覆盖，未变化部分复用 ToB-17 原版本证据。没有热改旧实例，也不声称 ToB-17 完整训练在 `8a3ef24` 上重跑过。

本次使用显式本机模型资料：ToB-17 为 Seed 2.1 Turbo/high；ToB-24 主轨为 GPT-5.6 Sol/max，伴随为 Seed 2.1 Turbo/high。GPT 的原生升级公告仅确认显示，实际模型未切换。GPU、模型和限定 AppArmor/seccomp 均按此次授权使用；这些许可不自动成为新题的默认权限。

## 2. 真实 Public/Dev 结果

| 题目 / 候选 | 完整训练 | 原始指标（越低越好） | 归一化分数 | 最佳保留 |
| --- | --- | --- | --- | --- |
| ToB-17 / 原始 Adam Starter | 100 epochs / 35,200 steps | error 5.68% | −0.1921182266 | 否，后由第二轮替代 |
| ToB-17 / Agent AdamW + warmup/cosine/clip | 同一完整协议 | error 5.06% | 0.1896551724 | 是 |
| ToB-24 / 原始 Starter | 60,000 steps | NLL 0.9856159069 | −0.0235287890 | 是 |
| ToB-24 / Agent Muon-Nesterov | 同一完整协议 | NLL 1.0442645794 | −1.6620292821 | 否 |

四个作业均成功、退出码为 0。ToB-24 两次训练分别为 2781.394 秒、2715.798 秒，随后各约 11.3 秒独立评分；原 grader 的训练与评分总预算仍为 7200 秒。外层 7260 秒守卫只给公开校验、传输、绑定和原超时清理留余量，不增加训练预算。

ToB-24 第二轮实际变差，Agent 正确保留原始 Starter；负分符合连续、不裁剪的评分公式，不是运行失败。四份结果都是有界验收的单 seed 结果，不证明新方法达到正式提升阈值，不替代原 B/R/U、五 seed 或长轨证据。

## 3. 实际验收与证据

| 能力 | 已核事实 | 原件定位 |
| --- | --- | --- |
| 合法启动与可视观察 | 两题使用原公开面和显式模型；原生 TUI 可只读观察。非 root、候选可写、受保护 auth/runtime 拒读，Docker socket 与私有 tests/reference 不可见 | 各实例 `preflight.json`、配置、原生运行日志；本地 README 的实际观察记录 |
| GPU 与真实公开入口 | GPU 6/4 的分配、身份和 CUDA 运算通过；Agent 经固定公开客户端提交，可信 worker 调用原科学入口，实际完成上述四份训练 | `runtime/jobs/records/`、`jobs/worker/<ID>/` 的快照、日志及结果 |
| 暂停与原会话恢复 | 两题各执行 pause→resume→pause→resume→stop；控制回执中的 thread、Goal createdAt、objective 均保持唯一。暂停时健康作业保留，恢复后查询既有结果，不重复训练 | `acceptance-controls.jsonl`、`runtime/logs/rpc.jsonl`、作业起止记录 |
| 两轨独立 | Seed CPU 启动、暂停、恢复、退出时，GPT container/thread/objective/job 均不变，作业一直 running，runner 日志 158→239→320 字节增长 | CPU 伴随 `acceptance.json` 的三次观察；GPT 对应作业日志 |
| 自主收口与合法操作 | ToB-17 的 8 个、ToB-24 GPT 的 3 个任务 turn 分别都属于各自原 thread；原 Goal 自主 complete。核原生工具记录，未见私有路径、旧 Broker、Docker socket 或另一轨内容调用 | `state.json`、控制回执、`logs/rpc.jsonl` |
| 材料与方法绑定 | 两题原始指标、候选、逐轮保留和 best_method 对应。ToB-24 两轮均为根 `rounds` + 八字段，中文摘要、UTC 日期、JSONL/JSON 内容一致，best_method 与首轮原 Starter 同字节，solve.sh 未改 | `runtime/output/`、候选 SHA 与实际源文件 |
| 可信 checkpoint 评分 | ToB-24 的两个实际 checkpoint 各 102,328,826 字节；实算 SHA 与训练/独立 scorer/最终输出一致。完整 15,971,840 个 Dev targets；scorer 未导入候选方法，原始指标及不裁剪公式和公开反馈一致 | `native_public/run/`、`train.log`、`score.log`、`runner.log`、结果文件 |
| 可复算时长 | 本轨实际 turn/job 区间取并集，均无 unresolved；ToB-17 为 6087.914 秒，ToB-24 GPT 为 6111.086 秒，Seed CPU 为 52.988 秒，均标记非正式 | `logs/activity.jsonl`、`logs/timing.json`；不以 Goal counter 代替净时长 |
| 生命周期清理 | 已完成的控制器/开发协调器退出，GPT 与 Seed CPU 原生容器均已删除；失败尝试单独保留，没有遗留本轮训练 | 控制 stop 回执、状态及完成后的只读进程/Docker 查询 |

ToB-17 测试提示曾错误要求数字 `time`，其 Agent 原件确有该格式问题。用户已确认归 Prompt/后续材料整理，不视为基座缺陷、不需重训；本次不改写原件，也不将它写为正式轨迹格式通过。共享正式模板和 ToB-24 真实输出均使用日期格式。

ToB-17 原训练结果的 `solution_sha256` 是原 loader 对“相对路径 + 文件长度 + 字节”计算的源码树摘要，不是 `method.py` 的单文件 SHA。两份源码树摘要均已按原算法复算，与训练/反馈一致；候选单文件 SHA 和最终最佳文件另行对应，不混用两种口径。

主模型活跃时间分别为 ToB-17 Seed 321.986 秒、ToB-24 GPT r3 575.199 秒、伴随 Seed 52.988 秒；它们与含训练的净区间时长不同。ToB-24 首个失败实例另约 138.52 秒模型活动，r2 在 thread/Goal/模型调用之前失败；失败记录未混入通过实例。上述活动均在各自有界许可内；原生 thread_title 辅助活动不算新任务会话。

## 4. 配置之外的改动与复用结论

| 实际缺口 | 分类、最小处理与验证 | 新题是否需要复制实现 |
| --- | --- | --- |
| 真实题短验收不应套正式 10h 门槛；有界共享许可原先只能到 preflight | 共享修复 `229e6e6`：`purpose=acceptance` 明确非正式，run 传递授权共享参数并拒绝用于 formal；ToB-17 两次真实训练验证 | 否，集中复用配置/CLI |
| 两题原入口和返回格式不同 | 题目薄适配：ToB-17 调原 `run_public_training`；ToB-24 调原 grader，并转发日志、校验绑定后转换 `completed`/标量 NLL。算法、科学协议、评分锚点不进入基座 | 只配置本题入口；已有入口不能直接满足合同时保留少量转换，不复制 worker/监督器 |
| 原严格候选检查与 Codex 临时保护目录冲突 | 共享修复 `baf2735`：快照只忽略并记录顶层空 `.git/.agents/.codex/.aws`，非空/嵌套目录和其他内容不丢弃；离线及真实沙箱回归通过。CPU 检查只复制两个原文件再调用原合同，不放宽实际评分检查 | 否，集中复用快照；特殊 CPU 合同包装留在题目适配侧 |
| 原生升级菜单阻塞只读 TUI，且配置 mode0444 不能原地追加 | 共享修复 `baf2735`、`8a3ef24`：native `model/list` 公告确认；原子替换 notice 并保持权限，模型/安全字段不变；真实只读权限回归及 GPT TUI 观察通过 | 否，集中复用显示兼容，不自动升级模型 |
| 开发协调器读到 tee 尚未写完的回执 | 仅本地验收工具容错：在有界期限内等待完整 JSON，不改生产状态/停止规则 | 否，不成为每题组件或门禁 |

原生显示字段依据为 [Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。宿主临时保护目录实为 0755，而沙箱投影只读，修复没有用宿主只读位作错误判断。中间错误、r1 训练前失败及 r2 配置写失败均保留原件，不计为通过。

共享最终修复时全库 **477 项通过（107.871 秒）**；ToB-17/24 薄转换器分别 2/5 项通过。收口另核来源、版本、控制身份、真实反馈和产物绑定，未调用新模型、GPU 或训练。Agent 一次 `git status` 因镜像无 git 返回 127，之后合法操作及训练继续完成；该辅助查询不是题目必需工具，不构成验收阻断。

结论：普通换题可复用同一基座的配置、原生 Goal/TUI、公开 worker、日志/计时及 GPU 兼容；保留的题目代码仅负责其原入口和结果合同。没有按题号硬编码，也未复用旧 Broker、daemon 或完整状态机。共性修复已进入共享源码，不需要每题再设计一套监督和恢复程序。

## 5. 原件与后续边界

- ToB-17：[`local/lp7t-tob17-20261009/README.md`](../../local/lp7t-tob17-20261009/README.md)，有效实例 `seed-gpu6/`。
- ToB-24：[`local/lp7t-tob24-20261009/README.md`](../../local/lp7t-tob24-20261009/README.md)，有效实例 `codex-gpu4-r3/`、`seed-cpu-companion-r3/`；r1/r2 为失败原件。
- 每个有效实例以 `source_binding.json`、`runtime/snapshot.json`、`acceptance.json`、控制回执、RPC/activity/timing、逐作业日志/结果和 Agent 自写输出相互取证，不另建审批或任务状态。

这些本地链接供维护核查，`local/` 不随源码/发行包分发。最终用户不需要阅读本记录或部署这些测试目录。

未声称覆盖：新的正式 7h/10h 双轨、五 seed 复验、新 B/R/U、平台 hidden、两题新版本完整 NOP/Verifier QA、全部任务类型或所有宿主安全策略；强制崩溃后的所有恢复组合也不由本次正常 pause/resume 推断。原生双镜像/NOP 的共享接入覆盖见 [LP-6](lightweight-lp6-20261009.md)，不把本次公开 worker 测试冒充最终 Trial。

**下一步是 LP-8**：按当前源码收窄发行物、核干净目录可用性及私有内容排除，再决定正式版本/tag 和已授权仓库同步。相关运行源码若在发布准备中变化，重验受影响路径；本次仅收口文档，没有打包、发布、push 或新增真实资源调用。
