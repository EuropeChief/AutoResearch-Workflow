# 原生 TUI 有界验收（开发中）

当前只完成离线接口检查，**没有通过真实 TUI 验收**；正式 `runtime run/resume` 仍使用现有 exec JSON 路径。这里不是每题必做流程，也不产生科研轨迹或 Hidden 分数。

验证目标：Harbor 0.23.0 创建和管理 CPU Agent 容器，在其中以 Codex 0.147.0 原生界面执行；专属 tmux 终端可只读观察/脱离；根据原生 rollout 而非 ANSI 画面识别回合、工具与等待输入；固定中性继续指令送入同一进程；外部中断后第二次启动明确恢复原 thread。

## 前提与运行

需明确授权实际 Seed 成本和累计时限，Docker 可用、现有 CPU pilot 镜像及 Harbor 安装均存在；不自动安装、不构建新镜像、不改宿主或容器安全策略。沿用 `local/model_profiles/seed.toml` 的显式鉴权引用；不使用宿主默认账号。本轮授权的限制是两次启动（首启和恢复）合计最多 1200 秒，不用 GPT/GPU，遇权限阻塞即停。

从流程仓根执行；使用未占用的 label，不覆盖旧运行：

```bash
python3 pilots/pca_cpu/prepare_runtime.py tui-probe-new
python3 pilots/pca_cpu/run_tui_probe.py \
  --task-root pilots/pca_cpu/runs/tui-probe-new \
  --allow-live --budget-seconds 1200
```

此入口只接受本 pilot `runs/` 下的合成任务，拒绝安全例外和 GPU 配置；保留 Harbor 原生容器归属，Verifier 明确关闭、重试为零。镜像/权限检查发生在读取鉴权和调用模型之前。目录已有 `tui_probe/` 时拒绝静默重跑，先核查原结果和剩余授权预算。

启动前重核冻结任务源码和 `task.toml` 的 CPU 声明，容器内再核没有 GPU 设备；不只相信旧配置。每一回合必须在原生记录中有精确 `/workspace/evaluate` 调用、成功退出和有效原始指标，Agent 自写记录与该回合结果一致，不能仅凭轨迹 JSON 格式正确而通过。

## 证据与局限

在新任务的 `tui_probe/` 下查看：`job.json`（实际 Harbor 调用）、`invocation.json`（来源和预算绑定）、Harbor trial 结果，以及 `evidence/report.json`、各分段原生记录/适配事件/计时/辅助屏幕快照。运行中各分段 `terminal.json` 给出只读 attach 参数；退出观察端不会被当成结束模型进程。

不对终端控制序列做日志解析。`RolloutTail` 跳过恢复前旧工作，并验证会话、版本、文件完整性与事件时间；未知记录保留原文，不补造开始/完成事件。当前原生记录适配限定单一主会话，探针明确不启动子 Agent；未验证的并行子会话不能自动合并进主轨迹。

合成测试覆盖错误间隔、未核实静默、长工具等待与压缩事件，但不能证明真实提供方都会输出相同事件。真实运行必须另外核对提供方错误是否可观测、原始公开输入/输出和工具结果是否齐全；若不足，P5A 保持未通过，不切换默认 TUI。原生记录时间用于短测时须落在宿主观测的分段范围，历史 session 元数据不计工作时长。

短测结束不会满足 10h 正式门槛。压缩未真实发生则标“未覆盖”，不得用合成压缩测试冒充；报告通过也不代表 P5B 的正式净时长、异常恢复和最终收口已经完成。

接口依据：[官方交互恢复说明](https://developers.openai.com/codex/cli/reference) 与锁定版本的 `codex --help` / `codex resume --help`。具体原生事件字段以本次锁定版本的实际记录为验收依据，不承诺跨版本兼容。
