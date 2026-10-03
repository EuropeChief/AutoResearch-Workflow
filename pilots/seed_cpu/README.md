# W5 Seed 真实 CPU 联调

这是通用工具的低成本测试夹具，不是标注题目，不产生科学结论、正式轨迹或质检通过结论。只调用中央配置的 Seed 模型；不调用 GPT、不使用 GPU、不运行独立 QA。

验证链路：冻结镜像和输入 → 真实预检 → Agent 修改公开排序方法并调用可信评测 → Agent 自写轨迹 → 监督进程中断 → 同一 thread 恢复 → 核对原始日志、分数、源码和时间记录。所有中断探针时长均不作为标注有效时长。

运行时数据在本目录的 `runs/`，构建上下文在 `build/`；不打入正式交付包。凭据仅从中央 Seed profile 的 auth_ref 读取，不复制到镜像和题面。使用本机已有 Python 基础镜像层和 Codex 二进制构建，不拉取新基础镜像。

本次联调采用有界调用，预检最多 180 秒，真实迭代和恢复各最多 180 秒，中断探针最多 20 秒。工具故障修复后的重试保留失败证据；总模型运行预算不超过 20 分钟。长上下文压缩、双模型科学公平性和完整 10 小时运行不在本次验收范围。

## 本机示例与验收边界

历史 0.1.0 联调完成版本是 `runs/trial02/`；`trial01/` 是保留的失败试验。原始设计报告归档标识为 `ca978de:W5_SEED_PILOT.md`，不是部署依赖。该联调仅证明当时 Seed 的短程预检、评测和同 thread 恢复，不证明当前 PCA 双镜像、GPT、GPU 或正式时长。新版适用范围见 [发布说明](../../RELEASE.md)。

只读结果复核（不调用模型，也不改写已保存的 verification.json）：

```bash
python3 AutoResearch新流程/pilots/seed_cpu/verify.py trial02
```

若在获得新的对应范围/预算授权后重做，使用从未存在的新标签，避免覆盖证据：

```bash
python3 AutoResearch新流程/pilots/seed_cpu/prepare.py <新标签>
python3 AutoResearch新流程/pilots/seed_cpu/exercise.py <新标签> probe
python3 AutoResearch新流程/pilots/seed_cpu/exercise.py <新标签> preflight
python3 AutoResearch新流程/pilots/seed_cpu/exercise.py <新标签> run
python3 AutoResearch新流程/pilots/seed_cpu/exercise.py <新标签> resume
python3 AutoResearch新流程/pilots/seed_cpu/verify.py <新标签> --write-report
```

`exercise.py` 经统一 CLI 调用真实 DockerBackend 和 Seed，不替换模型或评测器。
run/resume 各完成一回合后，在下一回合开始时发送中断；这仅是故障恢复探针，
不是正式标注中让 Agent 等待或反复无变化调用的策略。试验最终状态仍不足 10 小时，
W4 必须拒绝生成正式提交轨迹。

复现构建时，需要本机已有的 Dockerfile 基础镜像与 Codex 0.147.0 Linux 二进制资源；
将完整 vendor 目录放入 `build/vendor/`，把本目录 Dockerfile、evaluate.py 复制到 build，
再对该构建上下文执行 `docker build --pull=false --network none -t autoresearch-flow:seed-pilot-20260927 ...`。
此目录不保存或下载模型凭据。不要把 `runs/`、`build/`、Codex home 纳入任何题目的交付包。
