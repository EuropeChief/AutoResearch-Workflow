# 发布证据索引（维护者使用）

只索引真实原件，不增加每题记录或自动调用模型/GPU。默认运行包不带本文；旧 schema 1 留给历史收据，当前用 schema 2，不改写旧证据适配旧字段。

顶层：`schema_version: 2`、`release_version`、`limitations` 非空数组、`checks` 四项。各引用为 `{"path":"证据根内相对路径","sha256":"完整SHA-256"}`，禁止父目录跳转、绝对路径和符号链接。result 里的引用也相对索引根。索引可位于工作侧 `local/`，由工具从既有原件计算引用；不能公开此目录。

通过项字段：`id`、`status: passed`、`mode: fresh/reused`、`origin_version`、带时区 `origin_at`、`sources`、`evidence` 原件数组、`result` 定位索引、`reviewer`、`review` 和 `claims`。审阅记录说明授权、覆盖和限制；所有 claim 必须有依据，不能用填写 true 覆盖原件失败。

`sources` 用当时冻结原件，不运行后倒签清单：

- `{"kind":"runtime_snapshot","record":<真实snapshot.json引用>}`：核 `implementation/` 原件哈希、只读冻结及执行标志，依赖从当前入口静态展开，包括动态作业入口及资产。
- `{"kind":"harbor_snapshot","record":<真实report.json引用>}`：核同次 `program_files` 与冻结 `implementation/`。
- 独立入口试用的 `source_manifest` 绑定全运行包及同根 `implementation/` 原字节。

纯 `autoresearch_flow/__init__.py` 的 `FLOW_VERSION` 字面量变化可以复用，收据明确记录；除此之外，不忽略影响执行的源代码变化。CPU Harbor 的条件 GPU 路径由 GPU 项单独证明，不冒称 CPU 已测 GPU。

| id | claims | result 必要定位内容 |
| --- | --- | --- |
| native_runtime | native_tui, same_thread_resume, observer_detach, logs_and_timing, short_run_not_final | status=passed；state/activity/rpc/timing/trajectory 均为同一独立 runtime 的原件引用；observation_review 引用真实 TUI 观察/脱离审阅记录。工具核实际完成 Goal、同线程暂停恢复、新成功公开结果、净时长及 Agent 八字段轨迹；观察部分须据事实人工审阅 |
| harbor_transfer | candidate_transfer, independent_verifier, reward_retrieval | status=passed；trials 为当前源码的 CPU NOP 与有效候选 report 原件引用。程序只读重核相同 Trial 的 job/config/result/artifacts/reward/日志及 separate，不执行评分 |
| gpu_dispatch | authorized_devices, actual_gpu_execution, no_duplicate_jobs | status=passed；authorized_devices 为本次许可设备；admission 为薄 provider 实际 Docker/CUDA 探针原件；jobs 为独立公开入口的实际成功作业原件，核源码、设备声明、CUDA 运算与唯一 job ID |
| independent_trial | fresh_session, entry_sufficient, legal_pause_resume, no_unresolved_defects | status=passed；session_id、fresh_session=true、blocking_findings=[]、session_record 引用。审阅说明入口自足性及作者补充 |

只有独立入口试用允许本版明确例外：项内 `status: waived`、`mode: explicit_user_authorization`、`approval` 引用；不提供 claims/result。授权 JSON 必有 `kind: release_exception`、当前 release_version、scope=independent_trial、approved_by=user、日期、理由及用户明确原话；limitations 披露 independent trial waived。不能自动继承旧版本许可或豁免其他三项。

运行原件、授权和不可机械判断的观察仍须审阅；收据不宣称正式长轨、具体题目 QA、真实压缩或完整科研训练矩阵已通过。程序不需要读取 auth.json，不复制证据或凭据到发行物。
