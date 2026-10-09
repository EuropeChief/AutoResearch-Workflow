# 独立 Codex 运行底座

每次只处理一轨，不读取任务阶段、规则锁或另一轨状态。专家制作题目可用 Codex/Pi；正式轨迹由 Codex CLI 生成。新题使用[本轨配置模板](../templates/runtime.example.json)和[中文 Prompt](../templates/agent-prompt.zh.md)，旧 `--task-root` 接口不用于新实例。

## 输入与执行模式

使用者填写一个本轨 JSON 与显式 TOML 模型资料。个人 API URL、模型、推理档位和鉴权路径由使用者初始化；公开[模型模板](../model_profiles/)不带账号。准备不读取凭据，授权真实启动才读取，不继承制作 Agent 的账号。

JSON 指定镜像 ID/digest、Codex 版本、候选目录、公开映射、Prompt、固定公开命令与资源。相对输入路径基于 JSON 所在目录。两轨使用不同运行目录、设备和会话，不设整轨墙钟或额外 token 上限。默认各 36000 秒；完整满足不训练/单轮短例外者可在启动前设 25200 秒，并以 `duration.qualification` 引用资格说明。程序只查引用存在，不代替专家科学判断。

镜像已有 Python、题目依赖与公开数据、Codex 0.160.0；可选 `codex_vendor` 引用本机已有 vendor。宿主已有 Harbor 0.23.0、Docker/Compose、tmux 与标准 `websockets` 15.x；GPU 另需 NVIDIA Docker。底座不从零安装环境。

- `direct`：Agent 在真实 Codex 沙箱直接运行题目的公开程序；不启用跨权限作业通道。
- `worker`：需要合法沙箱外 CUDA/受保护执行的题目，用 `python /workspace/evaluate.py submit` 获得 job_id，再用 `status`、`logs`、`result --job-id 原ID` 查询。请求不能指定宿主命令、路径、资源。候选快照、日志、真实退出码与有限 score/raw_metric 绑定；独立作业监督进程不因模型暂停而退出。

题目仍须提供完整、独立的 Public/Dev 程序，不能只提交依赖本地协调器的客户端。worker 是按需能力，不要求每题使用 Broker。checkpoint 等产物位于本轨 jobs/worker/作业ID/output；所选必需模型由题目适配恢复至声明候选面，不可只留在缓存。

## 操作

在已有 Harbor/Python 环境和流程根运行：

```bash
python cli.py runtime prepare --config /task/seed-runtime.json --output-dir /task/runtime-seed
python cli.py runtime preflight --runtime-dir /task/runtime-seed --allow-live
python cli.py runtime run --runtime-dir /task/runtime-seed --confirm-cost
python cli.py runtime status --runtime-dir /task/runtime-seed
python cli.py runtime attach --runtime-dir /task/runtime-seed
```

attach 用本轨独立 tmux server 只读观察原生 Codex；Ctrl-b d 退出观察，不注入 Prompt、不取消 Goal/作业，也不依赖旧 tmux server 的用户组缓存。底座不因静默、训练等待、正常压缩或墙钟强停；Agent 自主结束原 Goal，complete 不等于时长和内容合格。

```bash
python cli.py runtime pause --runtime-dir /task/runtime-seed
python cli.py runtime resume --runtime-dir /task/runtime-seed --confirm-cost --prompt '继续原目标；先查已有作业，不能重复提交。'
python cli.py runtime timing --runtime-dir /task/runtime-seed
python cli.py runtime jobs --runtime-dir /task/runtime-seed
python cli.py runtime logs --runtime-dir /task/runtime-seed --job-id 原ID
```

控制器外部异常退出时，用 `runtime recover --runtime-dir ... --confirm-cost` 接管原容器/threadId/Goal，再按实际状态 resume。不能用 --last、新线程或替代 Goal；不重设 objective、不覆盖已刷新的登录副本。不能识别原实例时保留原件并报告，不接管他人容器。

`runtime stop` 只显式收口本轨且拒绝运行中或终态待核的作业。执行连接丢失时返回 `observation_pending`，不假称失败完成、不继续计未证时长，也不放行重复提交；定位本轨 supervisor log 与原件后再处理。可选 `evaluation.timeout_seconds` 是单作业限制，由固定 wrapper 清理自己的进程组并返回非零，不是整轨墙钟。`runtime finalize` 只核原 Goal 与净时长并交内容审查，不在本底座调用 Hidden。最终 Trial、artifacts 移交与独立 Verifier 是后续 Harbor 工作。

## 隔离与兼容

只挂载显式公开面、本轨候选/产物/Codex home/工作区，不挂整题根、参考解、另一轨或 Docker socket。根文件系统只读、非 root Agent、worker 另用 UID、命令网络关闭。凭据仅 Codex 父进程使用，工具不能读 /codex。题目镜像内部仍须正确隔离资产。

默认安全策略阻塞时返回实际阶段，不自动放宽。仅取得当前适用许可后可将 security 改为：

```json
{"mode":"codex_nested","authorization":"具体本次许可范围，不是永久许可"}
```

只引入限定 AppArmor 例外与默认拒绝的共享 seccomp，不使用 privileged、SYS_ADMIN、无限 seccomp 或关闭 Codex 沙箱。默认 GPU 占用即拒绝；allow-busy-gpu 只用于已获准的小型预检，不用于正式抢占。

## 记录与计时

运行目录包含 public、solution、output、codex_home、implementation、logs、jobs 与本轨身份。运行冻结程序副本，不向健康实例热替换共享修复。允许原生 TUI 的显示偏好变化，不允许实际模型/权限漂移。

logs/rpc.jsonl 保存实际暴露的消息、工具、输出、错误、用量/压缩通知，附接收时标并脱敏；codex_home 保留原生会话原件。不能承诺不可见推理或上游已截断内容完整。该目录含认证副本，不得整体上传。

logs/activity.jsonl 与作业原件可复算：真实模型 turn/健康作业取并集，明确错误/观察中断结束已证模型区间，健康作业单独保留；未知尾部不按墙钟猜算。Goal.timeUsedSeconds 不代替净时长。logs/timing.json 和只读 /run/autoresearch/responses/progress.json 给 Agent 进度，最终还须审内容合法性。

已证明无效区间用 `runtime exclude --runtime-dir ... --file ...` 追加，字段 start_at/stop_at/reason/evidence，原始日志不改写。`timing` 会按最近已保存的观察点重算，不填补离线或失去观测的间隔。预检不算正式时长。轨迹仍由 Agent 自写，原始日志只能审阅，不能替 Agent 编造方法记录。

Seed 可设 262144 上下文、160000 压缩阈值、65536 输出余量。前两项实际生成 Codex 参数，max_output_tokens 只校验压缩余量，不假称服务端输出限制。原生 Unix 控制通道为 WebSocket，标准客户端经 Codex proxy 连接，未自建 WebSocket 服务。[官方 App Server](https://learn.chatgpt.com/docs/app-server)

收口后可将已恢复的本轨 `solution/` 作为明确候选交给[原生 Harbor 评分入口](harbor.md)，不重新启动模型或依赖旧 Runtime/阶段状态。原件按[材料接口](materials.md)选取，不能整体上传含鉴权的本轨目录。

短合成验收不证明十小时稳定性、真实压缩或最终评分。[内部实施状态](maintenance/lightweight-lp5-20261009.md)
