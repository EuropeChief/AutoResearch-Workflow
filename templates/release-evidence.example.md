# 发布证据索引（维护者使用）

它只定位已有验收结果，不增加每题材料或自动启动实验。维护 Agent 从实际产物提取引用，审阅人核查不可机械判断的结论；不得预填通过或把下列示意值当真实证据。运行前保存当时 `release/source_manifest.json` 原件；其中须有文件内容与 mode，不能运行后拿新清单倒签旧证据。

索引 JSON 顶层：`schema_version: 1`、`release_version`、`limitations: [实际未覆盖范围]`、`checks: [四项记录]`。四项 id 及 claims 键见下表；只有已证明的键才能写 `true`。索引所在目录为证据根；所有引用用 `{"path":"根内相对路径","sha256":"完整哈希"}`，禁止绝对路径、`..` 与符号链接。各 result 内的引用相对该 result 文件所在目录。

每项记录字段：

| 字段 | 内容 |
|---|---|
| id / status | 下表 id；通过时 status=passed。只有 1.0.0 的 `independent_trial` 可经用户明确指示标为 waived；不能伪造结果或 claims |
| mode | 新验收为 fresh；复用为 reused。首发豁免项使用 explicit_user_authorization |
| origin_version / origin_at | 原运行版本与带时区 ISO 时间 |
| origin_sources | 原运行源码清单引用；相关源码与权限必须仍适用 |
| evidence | 非空原件引用数组，可直接引用已有报告、日志、原生事件 |
| result | 下表对应的结果定位 JSON 引用 |
| reviewer / review | 通过项须有具名审阅人及审阅记录，解释覆盖和限制；可共用一份短记录 |
| claims | 通过项中的键均为 true；它不能覆盖实际产物中的失败。waived 项不得提供 claims/result，须附 `waiver`（用户、日期、理由及授权记录引用） |

| id | claims 键 | result 内容 |
|---|---|---|
| native_runtime | native_tui, same_thread_resume, observer_detach, logs_and_timing, short_run_not_final | status=passed；state 指向真实 `.autoresearch-flow/runtime/seed/state.json`，trajectory 指向其 Agent 原件；jobs 为实际 Harbor job.json 引用数组；observer 为只读观察/脱离探针报告引用 |
| harbor_transfer | candidate_transfer, independent_verifier, reward_retrieval | status=passed；transfer_report 引用实际候选移交探针报告，含 trial.mode=separate、reward=1、候选哈希及原件 evidence |
| gpu_dispatch | authorized_devices, actual_gpu_execution, no_duplicate_jobs | status=passed；authorized_devices 为本次获准 GPU 标识；runs 中每项有唯一 run_id、execution 引用、cuda_result 引用 |
| independent_trial | fresh_session, entry_sufficient, legal_pause_resume, no_unresolved_defects | status=passed；实际 session_id、fresh_session=true、blocking_findings=[]、session_record 引用；审阅说明入口是否自足、是否需要作者补充 |

1.0.0 首发可以把上述 `independent_trial` 记录标为 `waived`，并在 `limitations` 明确“independent new-session trial waived for first release 1.0.0”。其他版本不得使用该例外；其他三项仍须提供真实原件并通过机械及人工审阅。

原生运行检查直接加载冻结运行配置、原件哈希、两段同一正式 thread、公开评测事件、Agent 八字段轨迹与 Harbor 配置；试验时长必须不足正式门槛，且 `final_snapshot` 实际拒绝，不能消耗最终查询。observer 报告须记录 `continued_without_observer=true`，且 segments 中至少一项 `observer_detached=true`。保留原生状态和相对目录，不把摘要替代整套可核原件；鉴权文件不需要交给发布工具，也不能公开打包。

有界连续运行允许在回答中途按预算暂停；恢复段须有自身的新成功公开评测且无原生错误，不能用首段成绩替代。不强制短测每段产生最终回答，不把 `budget_exhausted` 改写为 `completed`；短测通过只证明恢复后有真实工作，不能据此开放正式最终评分。

GPU 的 execution 原件须有 `exit_code=0`、`devices`；cuda_result 来自真实 CUDA 小程序，含 `cuda_available=true`、`matmul_finite=true`、`visible_devices`，与分配标识一致。不能用 GPU 型号文本或“nvidia-smi 成功”代替计算结果。不要求重跑完整科研训练。

自动检查只证明上述机械条件和绑定；审阅人仍核查运行授权、记录真实性、独立性和未覆盖范围。特殊 AppArmor 许可不会因通过发布检查而成为其他环境的默认权限。工具不复制原件或凭据，只将引用、哈希及覆盖结论写入验收收据。
