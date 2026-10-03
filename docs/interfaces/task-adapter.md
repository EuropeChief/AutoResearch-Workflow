# 题目适配边界与最小准备

通用程序已经提供状态、规则定位、正式实验账本、统计评分检查、双 Codex 运行与日志、证据整理和交付工具。每道题主要实现科学内容与可信执行入口，不重新实现这些通用模块。

## 新题由用户提供

- 明确任务目录、题目 ID/变体和任务卡。
- 论文、代码或可核来源链接；必要的数据访问条件与资源限制。
- 到模型调用阶段，再给已批准的账户/预算和凭据路径。凭据值不写入说明、Prompt 或题目证据。

正式规则默认来自中央 `rules/manifest.json`，无需用户为每题重填版本、日期和优先级。出现来源漂移时恢复该任务锁定的原版本；新规则用于新任务，不静默改锁，不把旧示例当正式规则。

## 专家实现的题目部分

| 部分 | 题目责任 | 对接通用模块 |
|---|---|---|
| 方法接口 | 定义输入/输出、允许修改范围、Baseline 和 Reference 源码 |实验工具`method_files` 必须含影响结果的源码和配置 |
| 环境 | Docker、固定依赖、离线 Public/Dev 资产、必要隔离、非 root 合法调用 |运行底座运行配置；最终 Harbor 环境仍遵从教程 |
| 训练/评分 | 公平预算、实际训练/推理、真实质量门和原始指标、连续评分 |实验工具的运行结果合同，运行底座 的评测 stdout 合同 |
| 模型证据 | 训练型逐 seed 模型、artifact、干净重载日志/指标 |实验工具校验引用；交付工具 接收已整理证据目录 |
| 研究说明 | 选题、代表性、改进归因、U 依据、局限 | `stage record` 的署名结论和原始证据 |
| 最终文档 | 题面、专家说明、标注 JSON、run_summary、comparison_summary |交付工具最小包构建；独立 QA 作最终包内检查 |

不规定每题训练代码的内部函数名称。`task configure` 的 adapter 是任务内实际入口文件引用，用于登记定位，不是动态插件；现阶段通用 CLI 不代执行该任意入口。真实运行使用题目自己的明确命令，运行前后用实验工具start/finish 登记。范例结构：

```text
题目根/
  inputs/                  # 题目卡、论文、来源
  research/                # 研究判断和必要探索记录
  workspace/harbor_task/    # 完整双镜像任务，不整体暴露给 Agent
    environment/           # Agent context；starter/public_eval/公开数据
    tests/                 # Verifier context；Dockerfile/test.sh/私有评分
  workspace/reference/
  evidence/                # 原始正式实验和专家决定
  records/                 # 专家填写的阶段/冻结输入 JSON
  runtime.json             # 引用通用模型配置，声明题目适配
  agent_prompt.md          # 两组共用的合法中文初始 Prompt
  .autoresearch-flow/      # CLI 生成；无需用户手建
```

这只是制作期布局；双镜像合同见 [环境接口](environment.md)。模型配置只在流程根的 `local/model_profiles/codex.toml`、`seed.toml` 中填写，runtime 配置 schema 为 2，不接受题目内 tracks 旁路。题面由 Harness 提供；本地组件预检可显式映射 instruction.md，不要求 task.toml 公开。Agent 每轮只调用 Public/Dev，/workspace/solution 可写、/workspace/starter 只读，私有 tests 不可见。Harbor 0.23.0 有限适配仍须按每题实际条件预检，不能以本地 Docker 路径冒充正式启动。

## 接口对照

正式实验使用 [实验工具](experiments.md) 中 `protocol → start → 题目命令 → result/envelope → finish` 合同。`start` 返回的方法/协议/seed 哈希须传入实际结果记录；账本时间不冒充执行时间。失败也保存日志和明确错误，不能筛掉失败 seed。

Public/Dev 入口使用 [运行底座](runtime.md) 的最后一行 JSON：`status/score/raw_metric`，评分必须由可信入口实际计算。Agent 面只暴露合法公开内容，不传入 Reference、Hidden 或其他轨迹。题目自己决定是否需要跨权限 Broker。

最终方法干净重跑需返回 `status/score/method_sha256/execution` 和日志，参考交付工具的 verification 合同。实验工具 的内部 result-envelope 并不自动成为项目方标准字段；准备最终 evidence 时按教程保留原始 result，不得手工重写原始分数。当前交付工具构建会核对包内逐 seed result 与实验工具原件哈希，因此来源应在正式运行时统一设计。

## 真实联调范围

每题须有目标 Harbor 独立环境、候选移交和出分实跑证据；同接口授权自验不代表官方 Hidden 通过。工具发布验收范围见 [发布记录](../../RELEASE.md)。
