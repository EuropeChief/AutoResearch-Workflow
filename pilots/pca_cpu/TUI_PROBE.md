# 原生 TUI 有界验收

离线接口和有界真实 Seed CPU 联调已通过；正式 `runtime run/resume` 已接入原生 TUI 并通过离线测试，新增真实监督联调仍待完成，不能用本探针代替正式运行。这里不是每题必做流程，也不产生科研轨迹或 Hidden 分数。

验证目标：Harbor 0.23.0 创建和管理 CPU Agent 容器，在其中以 Codex 0.147.0 原生界面执行；专属 tmux 终端可只读观察/脱离；根据原生 rollout 而非 ANSI 画面识别回合、工具与等待输入；固定中性继续指令送入同一进程；外部中断后第二次启动明确恢复原 thread。

## 前提与运行

需明确授权实际 Seed 成本和累计时限，Docker 可用、现有 CPU pilot 镜像及 Harbor 安装均存在；不自动安装、不构建新镜像、不改宿主安全策略。沿用 `local/model_profiles/seed.toml` 的显式鉴权引用；不使用宿主默认账号。首次启动与恢复共用获批预算（此入口上限 1200 秒）；新建目录不代表获得新预算，不用 GPT/GPU。

从流程仓根执行；使用未占用的 label，不覆盖旧运行：

```bash
python3 pilots/pca_cpu/prepare_runtime.py tui-probe-new
python3 pilots/pca_cpu/run_tui_probe.py \
  --task-root pilots/pca_cpu/runs/tui-probe-new \
  --allow-live --budget-seconds 1200
```

此入口只接受本 pilot `runs/` 下的合成任务，拒绝 GPU；保留 Harbor 原生容器归属，Verifier 明确关闭、重试为零。镜像/权限检查发生在读取鉴权和调用模型之前。目录已有 `tui_probe/` 时拒绝静默重跑，先核查原结果和剩余授权预算。

若预检被容器安全策略阻止，先停止并确认具体原因。只有取得**针对本次运行**的明确许可，才可在准备时同时传 `--allow-authorized-apparmor-exception --security-approval /本次授权原文.md`，运行时加 `--allow-security-exception`。该可选路径冻结授权原文和限定 seccomp 的哈希，仅对本次 CPU 容器设置 AppArmor 例外；不修改宿主，不使用 `--privileged` 或 `seccomp=unconfined`，不关闭 Codex 沙箱。历史许可不自动继承。

启动前重核冻结任务源码和 `task.toml` 的 CPU 声明，容器内再核没有 GPU 设备；不只相信旧配置。每一回合必须在原生记录中有精确 `/workspace/evaluate` 调用、成功退出和有效原始指标，Agent 自写记录与该回合结果一致，不能仅凭轨迹 JSON 格式正确而通过。

## 证据与局限

在新任务的 `tui_probe/` 下查看：`job.json`（实际 Harbor 调用）、`invocation.json`（来源和预算绑定）、Harbor trial 结果，以及 `evidence/report.json`、各分段原生记录/适配事件/计时/辅助屏幕快照。运行中各分段 `terminal.json` 给出只读 attach 参数；退出观察端不会被当成结束模型进程。

不对终端控制序列做日志解析。`RolloutTail` 跳过恢复前旧工作，并验证会话、版本、文件完整性与事件时间；未知记录保留原文，不补造开始/完成事件。当前原生记录适配限定单一主会话，探针明确不启动子 Agent；未验证的并行子会话不能自动合并进主轨迹。

合成测试覆盖错误间隔、未核实静默、长工具等待与压缩事件，但不能证明真实提供方都会输出相同事件。真实运行必须另外核对提供方错误是否可观测、原始公开输入/输出和工具结果是否齐全；若不足，P5A 保持未通过，不切换默认 TUI。原生记录时间用于短测时须落在宿主观测的分段范围，历史 session 元数据不计工作时长。

短测结束不会满足 10h 正式门槛。压缩未真实发生则标“未覆盖”，不得用合成压缩测试冒充；报告通过也不代表 P5B 的正式净时长、异常恢复和最终收口已经完成。

## 已取得的真实证据（2026-10-03）

运行目录 `runs/tui-public-20261003d/`（原始材料不随发行包分发）：Harbor trial `harbor_task__5Rjs6RN` 无异常，三次真实公开评测与三条 Agent 自写八字段记录逐轮一致，最佳代码与当前候选哈希一致。两分段共用原 thread，回合数为 2+1，已验证只读观察/脱离、原进程继续和原会话恢复。分段可观测工作时间合计 95.308 秒；不是十小时验收。未发生真实压缩。

本机无模型对照确认限定 seccomp 与 AppArmor 例外缺一不可，两层边界预检随后均通过。初次尝试 `tui-public-20261003b` 的恢复被工作目录信任页阻塞，保留失败记录；准备失败的 `c` 未调用模型。修复仅在生成配置中信任 `/workspace/solution`，其余文件权限、凭据拒读及工具网络限制未改变。两次真实尝试各设 600 秒上限，总上限未超过授权 1200 秒；均已清理容器。

成功报告 `tui_probe/evidence/report.json` 的 SHA-256：`8342701deb9fbacbace6246100c50404d6248f365229b380f0796b806eba72f3`。调用记录 `tui_probe/invocation.json` 绑定实际源码及本次安全授权，SHA-256：`2d3e1842a8124e056ef0eb7e477d0988701a3adffd5f108b9855f2bf066c72aa`。后续修改运行代码须按影响重新验证，不能仅复用此通过标签。

接口依据：[官方交互恢复说明](https://developers.openai.com/codex/cli/reference)、[项目级信任与沙箱配置](https://developers.openai.com/codex/config-reference) 与锁定版本的 `codex --help` / `codex resume --help`。具体原生事件字段以本次锁定版本的实际记录为验收依据，不承诺跨版本兼容。
