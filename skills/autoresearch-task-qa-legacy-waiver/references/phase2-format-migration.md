# 二期旧题迁移到当前交付格式

本批完整逐项审阅当前题包与已有研究内容，历史研究不重跑。二期旧包不是原样兼容：当前格式缺口必须补齐，缺 NOP、旧轨迹字段、历史卡型与新版指纹等记录差异另行豁免。

## 当前必须完成的调整

1. 当前 `task.toml` 必须采用目标平台有效的接口、资源和超时配置，明确 `separate` 及提交物移交契约。旧 `[resources]`、`[entrypoint]` 不能仅凭存在就当成当前配置；要迁移到当前有效配置，或已有实际适配入口将其转换并使用。GPU 内场选用 H20/L20，CPU 不加 GPU，移除不支持的配置。
2. 公开 Dev 入口及所需实现、数据继续提供给 Agent。旧 `tests/grader.py` 的公开部分需迁入 `environment/` 中的公开构建来源，可按已有公开接口等价命名；Agent 原生构建以 `environment/` 为 context，专用 Verifier 以 `tests/` 为 context，不能沿用任务根 context 混合 COPY。不能按文件名把公开 Dev 一概判为私有，也不能把私有 tests/ 提前复制给 Agent。
3. 独立 Verifier 具有可定位的正式评分入口、必要实现和依赖准备方式。原 `test.sh` 若只跑 pytest/接口测试，必须接上真实的最终评分并输出正式 reward，不能只凭合同测试成功算完成。
4. Hidden 私有材料必须有实际来源及评分读取关系。可以随私有构建上下文交付，也可按已有交付方案生成或安全后注入；不能仅放空目录而没有来源、投放路径和调用关系。
5. Agent 最终提交位置、artifacts 移交、Verifier 接收位置和 grader 读取路径必须一致。不能依赖 Agent 临时安装、缓存或未移交文件。
6. 两侧采用不同 sandbox，各自单容器，不使用 Compose 或额外工作环境。当前文件、COPY 上下文、依赖声明和入口错误须修，平台镜像构建、启动与实际 Harbor 验证另行完成。

## 仅供质检员：已有配置适配的说明

优先直接核对已迁好的当前原生 task.toml。若交付中已有真实适配入口及同一任务根内现有的原生目标 TOML，质检底稿可用 `config_adapter={entrypoint,effective_task,summary,evidence}` 引用并核对实际调用与字段映射。另一套已生成的任务目录直接以 `task_root` 选择，不用此字段切换当前任务。

旧 entrypoint 仅为历史说明且已由当前入口替代时，可用 `legacy_entrypoint_inactive={summary,evidence}` 引用已有配置、适配源码和启动入口，逐项核对未再使用；可与仅转换资源的真实适配方案并用。实际仍调用的旧路径继续检查。简单字面执行位置可静态发现，复杂或间接调用仍由 F01 根据源码核对，不能仅凭文字声称生效或失效。这些都是可选审核解释，不是专家新增 schema、文件或运行日志。

## 本轮不追加的历史工作

不要求补做旧批次未交的 NOP，不要求为了新格式重跑历史 Agent/Baseline/Reference、倒填八字段或改造旧日志，不要求历史版本指纹等于返修包。已有三门控、正式结果和双轨内容仍须逐项审阅。保留真实旧记录，不能把旧成绩标成当前新配置实测。

## 来源核对

- 二期教程 `P1J5dgIw1oKchcxn29GcvzlMnSd` 历史 revision 221：单 Dockerfile、公开 tests/grader.py、外部注入 Hidden，以及两字段轨迹。
- V4 教程 `LjN0dthKPo8QCcxSW9LusQJasCg` revision 51：separate、独立 sandbox、有效镜像/构建方案及 artifacts 移交。现文明确允许镜像复用、省略 tests/Dockerfile；目录树是专用 Verifier 构建示例，不能仅据树图认定统一必交两份。
- 算法标准 `Th1ydNXiXoa59lxJrg0uYSnlsdc` revision 1724 与内场 runner 指南 `MOP9d9m57oMxN1xlBfecbXUtnWe` revision 2190：未查到统一两份 Dockerfile 必交条款。本次先按上述现行已核实分支执行；若本批后续明确统一双 Dockerfile 交付，须同步标明新增口径，不能伪称来源原有要求。
