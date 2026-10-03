# PCA 双镜像与 Harbor CPU 短试验

只用合成数据核对两个独立构建 context、Agent 无私有 tests、公开出分、Verifier 降权执行候选、私有读写拦截、任意 cwd 正式入口和可信 reward。不是正式题目或通用安全沙箱。组件/移交试验不启动模型；单独的 runtime pilot 经授权调用 Seed，不用 GPU、不做 10h/12h 测试。

显式指定已存在的本地 Python 镜像并允许 Docker 后运行 `python3 run_components.py --base-image 本地镜像 --allow-docker`。会新增两张共享基础层的组件镜像和 runs/ 记录，不清理或停止其他任务容器。此合成 grader 不供真实题目原样复用。

`task.toml` 中的镜像 ID 是本机记录，不是跨机器可用的公共镜像。`run_harbor.py` 从组件报告取当前 ID，校验 context 摘要，将 instruction.md、task.toml、environment/、tests/ 单独复制；不要将 build/runs 当作任务输入。Harbor 0.23.0 为用户暂定目标，进度见 [实施记录](../../../AutoResearch新流程设计/PCA_IMPLEMENTATION_STATUS.md)。CLI 退出码 0 不足以判成功，须检查 trial 异常、实际独立环境和 reward。

```bash
python3 run_harbor.py --harbor-bin /本机虚拟环境/bin/harbor --docker-config /本机专用Docker目录 --component-report /本次组件/report.json --allow-docker
```

此命令使用 TransferProbe 在实际 Agent 环境替换候选，核验 artifacts 哈希及独立评分；不调用模型。每次建立新记录，不覆盖失败记录。Harbor 会运行时改变日志目录，可信入口必须恢复候选不能写 reward 的权限，并保留宿主日志读写能力。

`prepare_runtime.py` 是维护环境专用 fixture，包含本机镜像标识，不能当通用新题模板。它创建独立 runtime 题目，复用中央模型配置，然后通过 CLI preflight/run/resume 做有界 Seed 测试。`--allow-authorized-apparmor-exception` 只能在已有适用授权时使用。本次许可仅针对 CPU pilot，不能向其他题目传播。

runtime02 已通过公开预检、原会话恢复和一条八字段记录，预算耗尽时进入下一轮；应作为暂停状态保留，不能算最终最佳恢复完成。完整运行目录可能含鉴权/会话数据，不可整体上传或迁移。
