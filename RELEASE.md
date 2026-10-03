# 发布状态与维护验收

## 当前工作树：解耦修订，未正式发布

2026-10-03 的源码包含 OP-0—OP-3 和包修订 `2026-10-03.decoupled`。流程状态/API 版本保持 `0.2.0`，不改变已有任务的六阶段语义。正式新版迁移发布仍归 OP-8；OP-4—OP-7 不因解耦而视为完成。

设计仓库不再是当前部署依赖。必需的规则提炼快照已放到 [rules/provenance](rules/provenance/README.md)，教程和完整 QA skills 仍按 [部署说明](DEPLOYMENT.md) 集中提供。当前 [源码清单](release/source_manifest.json) 和 [离线验收](release/acceptance.json) 不代表新的 Docker/模型运行或平台批准。

## 历史发布证据

2026-09-30 的 0.2.0 PCA 发布验证过：Harbor 0.23.0 候选 artifacts 移交、独立 Verifier 与 reward；Seed 有界 CPU 预检、同一 thread 恢复及 Agent 自写八字段记录。未调用 GPT，未验证 GPU、完整双轨时长、长上下文或平台 Hidden。Harbor 版本是用户暂定兼容目标，不是项目方统一版本声明。

该次发布及 QA v0.3.1 更新的原始记录已保留：

- [解耦前发布说明](release/history/20261003-pre-decoupling/RELEASE.md)
- [原验收与原始证据索引](release/history/20261003-pre-decoupling/acceptance.json)
- [原源码清单](release/history/20261003-pre-decoupling/source_manifest.json)
- [0.1.0 发布历史](release/history/0.1.0/RELEASE.md)

历史快照内的路径、版本、链接与结论是当时记录，可能指向本机 pilot 或设计资料，不作为当前部署的依赖或操作指令。历史验收不得被改称本次真实联调。需要追溯完整设计说明时，可在设计仓库按初始 commit `ca978de` 查找 `PCA_IMPLEMENTATION_STATUS.md`、`W5_SEED_PILOT.md`；新环境不需要这些文件。

## 维护者检查与发布

从中央根执行：

```bash
python3 AutoResearch新流程/tools/release_check.py
```

默认只进行源码语法、规则哈希、活动文档链接、全量测试和异路径部署检查；不读取 pilot 运行原件，不发起 Docker 或模型调用。重定位根只含流程、教程和 QA skills，没有设计目录、宿主配置、凭据或运行原件。原样规则溯源快照按 SHA-256 核对，历史链接不参与活动导航检查。

检查通过后更新当前源码清单与离线验收，`release_ready=false`。工具在写入前将被替换的旧清单/报告保留到内容寻址的 history；相同记录不重复归档。离线输出不能直接通过正式迁移发布门禁。

如需仅验证未发布源码的打包/解包链路：

```bash
python3 AutoResearch新流程/tools/build_migration.py --preview --output-dir /显式预览输出目录
```

产物名称和报告明确带 `preview`，不覆盖正式包，不声明 `release_ready`。预览仍要求当前源码与已通过离线验收的清单一致，并完整重跑解包哈希、规则和测试。正式打包不加该参数，依旧只接受 `release_ready=true` 的当前发布验收。

正式发布使用现有 `--release` 路径绑定真实有界联调证据；仅 QA 修订且运行源码/原始证据完全未变时才可用 `--release --reuse-prior-live`。缺少真实证据或哈希变化时不得豁免。当前增量尚未完成 OP-8，不能把历史证据复用限制放宽为自动通过。

## 使用者边界

每题无需重复维护者全套发布检查。遵循 [START_HERE](START_HERE.md) 与当前阶段说明，进行题目自身的真实环境/双路 Public/Dev 预检、合法独立迭代和最终包独立 QA。默认时长及资格例外以 [OP-3](OP03_DURATION.md) 的冻结政策为准。历史 CPU pilot 的 AppArmor 例外不能自动移植到新机器或正式题目。

旧任务的路径迁移、版本边界和回退见 [解耦说明](DECOUPLING.md)；Git 初始提交不是正式发布 tag。
