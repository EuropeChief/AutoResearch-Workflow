# 发布状态与维护验收

## 当前版本

**0.3.0 开发中，未正式发布。** 当前来源自包含、schema 2 仅面向新任务；后续阶段检查、模型本地配置、TUI、并行复验及归档收口仍按批准计划实施。不要以旧版验收宣称当前快照已通过真实联调。

教程与两个完整 QA Skill 已纳入仓库，见 [部署说明](DEPLOYMENT.md)。历史规则提炼记录不是运行依赖。`release/source_manifest.json` 与 `release/acceptance.json` 在重新生成前只代表其记录的旧快照，不代表当前工作树。

## 维护者离线检查

在流程根执行：

```bash
python3 tools/release_check.py
```

默认检查源码语法、规则哈希、活动文档链接、全量测试和仓库单独异路径部署，不启动 Docker/模型或读取 pilot 运行原件。原样官方 Skill 中指向待审任务的示意链接、历史快照链接不当作本仓导航。

通过后生成当前离线清单与验收，`release_ready=false`；被替换的旧记录按内容归档。此结果只证明离线合同，不代表正式发布。

仅在需要验证归档链路时：

```bash
python3 tools/build_migration.py --preview --output-dir /显式预览输出目录
```

预览要求当前源码匹配离线清单，并重跑解包校验；产物明确标为 preview。正式发布工具中的真实证据入口尚待本轮维护改造，当前不要用历史固定 pilot 路径或旧 `--release` 结果为新版本背书。

## 历史证据

2026-09-30 的 0.2.0 PCA 发布曾验证 Harbor 0.23.0 候选移交、独立 Verifier/reward，以及 Seed 有界 CPU 预检与同会话恢复；未验证 GPT、GPU、完整双轨时长、长上下文或平台 Hidden。该 Harbor 版本是本地有限兼容目标，不是项目方指定通用版本。

- [旧发布说明](release/history/20261003-pre-decoupling/RELEASE.md)
- [旧验收索引](release/history/20261003-pre-decoupling/acceptance.json)
- [旧源码清单](release/history/20261003-pre-decoupling/source_manifest.json)
- [更早的发布记录](release/history/0.1.0/RELEASE.md)

这些记录保留当时路径和事实，不是当前操作指令或部署依赖。

## 使用者边界

每题无需重跑工具全套发布测试，但须完成题目相关预检、合法独立迭代及最终包独立 QA。见 [START_HERE.md](START_HERE.md)。历史安全例外不得自动移植；旧任务使用原版本，当前不迁移其状态。
