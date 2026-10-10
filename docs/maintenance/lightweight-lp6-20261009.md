# LP-6：原生 Harbor 最小接入验收

日期：2026-10-09。状态：LP-6 内部验收完成。基线 `ee4df87`；没有发布新版、上传 GitHub、修改已交付题目或接管历史轨迹。

## 实际交付

- `harbor run` 输入实际题包、可选明确候选、Harbor Python 与新输出目录；不读 TaskStore、阶段登记、旧 Runtime 或另一轨状态。不传候选即原生 NOP。
- 目标安装的 Harbor 0.23.0 真实 Task/Job schema 校验；原生 CLI、Docker 双镜像、绝对 artifacts、独立 Verifier 和 reward 回收。候选适配器只装入所选源码/模型/配置，不调用模型、不选择方法。
- 题包、候选和运行程序冻结，保留原目录名、实际资源/时限、Job 配置和同次原件。构建路径复用官方只读解析器，manual 范围不冒称自动通过。
- 核原生异常、有效覆盖与顺序、真实移交清单、有限 reward 原件及 Harness 接收值。JSON reward 优先；零/负分合法。CLI 退出 0 不能掩盖 Trial 失败。
- `harbor inspect` 只读复核原件、冻结程序和当前可选题包/候选；不重新评分。日常输出只给结论和完整记录位置，不重复整份清单。
- 新运行底座已恢复的 `solution/` 可直接作为候选；新材料接口可导出同次 Trial 原字节，不上传整个运行目录或含鉴权的 Codex home。
- CPU 采用原生 Docker provider。GPU 仍按需复用 LP-5 薄扩展；此次仅增加明确零 GPU 阶段不分配设备的兼容，不改原默认合同，没有 GPU 真实 Trial 验收。

日常使用见[原生 Harbor 说明](../harbor.md)。本维护记录不是每题额外验收表。

## 验证与问题关闭

修改前全库 **443 项通过**；最终全库 **458 项通过，103.106 秒**。新增 15 项覆盖复制/Git/凭据/链接边界、完整模型产物、reward 优先与有限性、失败/覆盖/时序、原件复用、防改写、材料原字节、独立 CLI、零 GPU 阶段、配置校验超时及合成 grader 写入顺序。

Standards 和 Spec 两轴只读审阅完成。前者发现 schema 超时丢诊断，已先复现后改为保留日志与结构化失败；后者指出配置只被移交而未被使用，已改为有效候选实际读取 coefficient、无配置候选明确失败，最终实测闭合。

Skill 小幅接入按 skill-creator 保持为一个使用说明链接；格式校验通过。允许列表与文档链接检查通过，`local/` 原件不入分发。没有重新生成发布收据或迁移包。

## 有界真实 CPU 原件

使用既有合成镜像；未重建镜像、调用模型/GPU、训练或改变宿主安全策略。Harbor **0.23.0**、Compose **2.39.4**。构建上下文与历史构建原件 `pilots/pca_cpu/runs/20261003T163251Z/report.json` 完全对应：

- Agent ID：`sha256:42c389a5008711df3f9f23794435bbf99ea2f217db685937cc0165ef2b0fa19a`。
- Verifier ID：`sha256:e9d809aa32a217542e448113af9d1ddef59e0d953714fbf218883c9a618b57b2`。
- environment context digest：`69656765f345b48ee9217852e0d0d72defd6e0652478c47fde4affef4e376337`。
- tests context digest：`ace34daeec99d7dec08a3e222703a2b3ebcd60d1510bcf4251595493fcb8408e`。

此前合成 task.toml 仍指旧 Verifier 镜像，现修为以上与当前上下文对应的 digest。只读 Docker image inspect 确认 ID 存在；原生 Trial 使用该配置并实际运行。原生 result 没有通用“实际容器 image ID”字段，不把配置记录冒称独立容器审计。

原件位于工作侧 `local/lp6-native-20261009/`，不分发。各目录保留原生 config/result/reward/log、候选 artifacts、冻结实现和自动 report。最终三个 Trial 的冻结运行程序哈希与当前源文件一致，其中 `harbor_native.py` 为 `2122518ef96968fc535f7860aa95af4c9cae913b1d0ed8081507d0695773d915`。

| 最终原件目录 | 原生 Trial | 结果与实际覆盖 |
| --- | --- | --- |
| `final-nop` | `pca_cpu__K6A47zG` | 原生 nop、separate、起点移交及 reward=1；33.825 秒。只证明该 NOP 分支 |
| `final-valid` | `pca_cpu__kprAcQU` | 所选源码与必需 model.json 原样移交；配置参与预测、候选拒绝私有评分文件及 reward 写入；原生 reward=1；34.012 秒 |
| `final-invalid` | `pca_cpu__3FNBu66` | model.json 故意缺失，Verifier 日志真实 FileNotFoundError；无 reward，原生 RewardFileNotFoundError；Harbor CLI=0 而工具正确失败；34.087 秒 |

首次三条中间版 `nop/valid/invalid` 原样保留，不称为最终源码实测。六条原生 Trial 时长累计 **204.427 秒**；最终三次外层记录合计 **121.262 秒**（含命令启动/回收）。连同首次短启动开销仍在本次累计最多 600 秒授权内。验收结束只读 `docker ps` 为空；没有操作他人容器。

最终 NOP/有效候选又经 `harbor inspect` 核当前题包、候选及冻结实现，原件未被改写。失败日志记录在原生 `verifier/test-stdout.txt`，不能因名称而忽略其中实际 stderr。

合成 grader 源码和 AST 回归确认：执行候选之前删除两种 reward，成功后 `os.replace` 原子替换；有效分支实际证明候选不能写 reward，失败分支不留下成功 reward。未额外注入预写结果或模拟断电，不声称覆盖这些未做的实验。

## 限制与接续

本次是 CPU 合成链路，不是科学锚点、训练模型质量、完整五 seed、长轨稳定性或真实题 QA。`model.json` 是合成必要配置，不冒称训练 checkpoint。镜像内部可见 Git 和 grader 安全仍由具体题目实现。

LP-7 收口旧 CLI/模板及回归；LP-7T 再在 ToB-17/ToB-24 隔离副本分别验证真实公开入口、实际产物与必要 GPU 原生链路。真实模型/GPU/安全例外按新的适用授权执行，本次 CPU 许可不继承。
