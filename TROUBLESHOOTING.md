# 故障和返修：按证据处理

先运行 `task check` 与 `stage status`，报告实际错误码、任务目录、受影响步骤和证据路径。不要直接编辑账本、删除历史或复制另一题的“已通过”状态。

| 现象 | 处理 |
|---|---|
| `TASK_NOT_INITIALIZED` | 核用户给出的题目根；新题明确授权后 init。不要推断或迁移旧 `.autoresearch/`。 |
| `SOURCE_DRIFT` | 回查原件差异和 manifest；修好中央来源锁后预览 `task upgrade`，确认影响再显式 `--apply`，重验受影响结论。 |
| `EVIDENCE_DRIFT` / `STALE_STEP_RECORD` | 查对应 receipt，确认是错误修改还是有意修订。从最早受影响步骤 reopen；旧原始结果仍保留，不修改哈希掩盖变化。 |
| `STEP_ORDER` / `STAGE_INCOMPLETE` | 看 status 的 next_step，补实际工作及证据；不能仅填 passed。 |
| `STEP_FROZEN` | 已通过步骤不可直接覆写；需要返修时 reopen，生成新记录。 |
| `PROTOCOL_MISMATCH` | 检查 B/R/最佳方法是否同协议、同切分和正式 seed。科学协议有变更时退回冻结阶段，不能换算拼接不同实验。 |
| B01–B08 未通过 | 缺证补证、实现故障修复；参考方法依赖仅 B03/B07 当前部分已过时可延至阶段 3。 |
| 3σ–5σ `needs_review` | 追加同协议两侧 seed，全部参与统计；仍在此区间时绑定统计解释并标记平台复核。不要改弱 Baseline 或反推 U。 |
| `SANDBOX_FAILED` | 无模型探针已发现 Codex 内层沙箱不可用。先查看 boundary.json；核 Docker 的命名空间与挂载限制，不关闭 Codex 沙箱绕过。只有明确授权后才配置限定的 docker_security，重新 prepare 独立运行版本，不热改旧会话。见 W3_RUNTIME.md。 |
| 真实预检失败 | 从对应组日志定位模型/权限/评测入口，不把普通终端 ping 当预检通过；只修受影响部分后重测该路径。 |
| Agent 外部异常 | 保存日志，剔除停滞；监督进程未收口先 recover，再用原 thread resume。不能新会话拼接。 |
| 轨迹缺失或不符 | 从 Agent 自写 JSONL 原件核对；可证实的格式/表述错误按 W4 修订，缺失的真实尝试不可推测补写。 |
| QA 报告路径/包哈希不符 | 确认最终包根目录；新包用 qa-handoff 重新交接，用户新会话独立质检。不重新绑定旧报告冒充新包通过。 |
| QA 需返修 | 逐项核原文和证据，合理反驳须据原文；修复从最早受影响步骤 reopen。仅材料修订不自动重训；复用未变方法及协议的证据。 |

提交前最后确认：使用当前包版本，轨迹有效时长有依据，B/R 原始逐 seed 结果及训练型模型齐全，最终方法可复现，包内不存在旧题面解释或与当前分数矛盾的材料。独立报告中任何本地未关闭问题都必须如实登记。
