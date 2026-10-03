# 发布状态与维护验收

## 当前版本

**0.3.0 开发中，未正式发布。** 仅面向新任务和匹配版本接续。当前能力与验证边界如下；不以离线或局部短测宣称整题/平台验收通过。

| 能力 | 当前证据与限制 |
|---|---|
| 规则、状态、实验/评分、QA 后三包及填表 | 离线合同与异路径部署可核；科学结论仍须实质审查，QA 在独立会话进行 |
| 原生 Codex TUI、预算暂停、同会话恢复、只读观察 | 当前 native_tui 政策下新建 Seed CPU 任务，预检与两段同会话实测通过，见 [证据与局限](pilots/pca_cpu/TUI_PROBE.md)；未修改旧冻结记录，不代表十小时正式轨迹通过 |
| 有限本地复验队列 | CPU 合同及[两卡 GPU 实测](pilots/gpu_queue/README.md)通过，串并行同结果、完成后无重复启动；不据此宣称共享卡独占或 Harbor GPU provider 已验证 |
| Harbor 双镜像评分链 | 当前源码的 CPU 合成验收完成候选移交、独立 Verifier 与 reward 回收；不是正式 Hidden 数据验收 |
| 环境适配 | Harbor 0.23.0、Codex CLI 0.147.0 为已适配目标；每题镜像/资源/provider 均须预检，其他版本不自动兼容 |
| 完整发行 | 入口与领域文档已归位；当前证据绑定和[独立新会话试用](pilots/entry_trial/README.md)全部满足后才正式发布；GPT、真实压缩与正式长程未由 CPU 短测证明 |

更新规则、接口或处理使用反馈时，先读 [维护说明](MAINTAINING.md)；它不增加每题操作步骤。

教程与两个完整 QA Skill 已纳入仓库，使用方式见 [README](README.md)。`release/source_manifest.json` 与 `release/acceptance.json` 在重新生成前只代表其记录快照，不代表当前工作树。

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

预览要求当前源码内容与权限匹配离线清单，并重跑解包校验；产物明确标为 preview。只打包当前单仓、锁定的教程/Skill 原件和本次两份验收收据；不包含历史收据、真实运行原件、个人配置或设计仓。文件执行权限、中文路径、解包文件集合与哈希必须一致。

## 显式发布证据

由维护 Agent 在实际验收后整理一份证据索引，不要求使用者逐项抄写结果。格式和各类原件见 [证据模板说明](templates/release-evidence.example.md)。索引放在本地验收材料目录（例如被排除的 `local/release-evidence/`），不放进源码发行物；路径相对索引所在目录，必须能定位真实原件和原运行源码清单。

```bash
python3 tools/release_check.py --release --evidence-manifest /本次验收目录/manifest.json
python3 tools/build_migration.py --evidence-manifest /本次验收目录/manifest.json --output-dir /新发行输出目录
```

没有显式证据，`--release` 在运行测试前即拒绝。必须覆盖原生 TUI/正式监督与恢复、Harbor 独立评分、实际 GPU 分配及新会话独立试用；任意一项缺失、失败或原件漂移均不能正式发布。机械检查读取真实输出中的会话、评测、Verifier 开关、短跑门禁、reward、设备与计算结果；独立试用的语义结论仍由具名审阅人负责，不把格式正确等同于实际成功。

每项保留原版本、时间、fresh/reused、原始源码清单与审阅记录。相关 Python 依赖、CLI 入口、实际非代码输入和权限变化使旧证据失效；不相关维护文案无需重跑模型。运行记录中的来源路径仅用于追溯，实际账号信息不进入发行物。原始索引/产物在检查与归档时都重新校验；打包不调用模型或 GPU。

历史验收保留在维护仓 Git 与本地 `release/history/`，但不作为新版本默认依据；不再使用固定日期目录、`runtime02` 或隐式 `--reuse-prior-live`。旧收据 schema 不升级成通过记录，须重新执行本次离线检查。缺授权或独立试用时保持未发布，预览包不能冒充正式包。

## 使用者边界

每题无需重跑工具全套发布测试，但须完成题目相关预检、合法独立迭代及最终包独立 QA。见 [START_HERE.md](START_HERE.md)。历史安全例外不得自动移植；旧任务使用原版本，当前不迁移其状态。
