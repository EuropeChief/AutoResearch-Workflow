# AutoResearch 标注流程

供专家 Agent（Codex 或 Pi）驱动的题目标注工具：从研究探索、Baseline/Reference 验证，到双 Agent 迭代、最终方法复验、独立质检和交付。用户负责关键科学冻结与必要授权，程序负责可重复检查和留证。

**当前版本为 1.0.0。** 已验证能力、范围限制及首发例外见 [发布状态](RELEASE.md)。仅支持新任务和匹配版本的接续，不迁移旧任务。

## 准备条件

完整克隆或解压本仓库即可定位教程、附件和两个完整项目方 QA Skill；内部布局保持不变，外层目录可改名。题目与流程包分开存放，不复制通用程序到每一道题。

| 到哪个阶段 | 需要什么 |
|---|---|
| 开始研究 | Python 3.11+、Git、明确的题目目录及题目卡/论文/代码或可核链接 |
| 环境与实验 | 已可用的 Docker、Compose/Buildx、任务依赖和合法数据；GPU 题目再核设备及 NVIDIA 容器支持 |
| 双 Agent 迭代 | 可调用的 Harbor 0.23.0、含 Codex CLI 0.147.0 的任务镜像、宿主 tmux、两组模型账号和预算 |

这些是当前适配条件，不是项目方指定通用版本。本工具不从零安装宿主环境，不自动改驱动、服务、用户组或安全策略；缺项时说明具体操作，由用户处理。账号到迭代前再配置，不阻塞选题研究。

在流程根检查可用性：

```bash
python3 cli.py --format json version
python3 cli.py --format json rules check
```

来源缺失或哈希不同应恢复匹配原件或按维护机制审查更新，不直接改哈希放行。

## 开始新题

在独立、已存在的题目目录准备题目卡、论文、代码或链接。向专家 Agent 提供：

> 请读取 `/流程根/START_HERE.md`，处理新题目录 `/题目根`。我授权为该新题初始化流程状态。按当前步骤推进，科学冻结、高成本运行及其他必要授权按流程处理，不引用其他题目的状态。

后续继续同题时仍提供这两个路径，Agent 按任务状态恢复。安装插件不是前提；可直接读取 [薄 Skill](skills/autoresearch-workflow/SKILL.md)。如安装，使用宿主支持的目录注册或链接方式，保持完整流程包与相对路径，不单独复制一个 SKILL.md。

两份模型公开样例位于 `model_profiles/`，实际配置放在 `local/model_profiles/codex.toml`、`seed.toml`。不要覆盖已有配置；密钥使用外部文件引用，不放进说明、Prompt、日志或交付包。具体操作到阶段 4 再读 [运行接口](docs/interfaces/runtime.md)。

## 按角色阅读

- 执行标注：[START_HERE.md](START_HERE.md) → [六阶段导航](docs/stages.md)，仅按当前步骤读取接口。
- 处理错误：[故障与恢复](docs/troubleshooting.md)。
- 更新流程程序、规则或模板：[MAINTAINING.md](MAINTAINING.md)。

任务状态在题目 `.autoresearch-flow/`；教程原件在 `sources/tutorial/`，QA Skill 在 `skills/`，规则定位与优先级由 `rules/manifest.json` 和 `rules/catalog.json` 提供。无需逐题手填来源版本。

程序核验不代替科学判断、真实实验或独立 QA。最终 QA 由用户在新会话运行，只取证确定版本的最终提交包；通过后才压缩三包并生成填表材料。
