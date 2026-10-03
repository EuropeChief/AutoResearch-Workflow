# PCA 双镜像：制作合同与验收接口

适用 PCA-20260929 教程。本文件说明已实现的结构/证据接口，不表示 Harbor 驱动已实现或本地联调已通过。当前开发状态见 [RELEASE](RELEASE.md)。

## 两个环境与职责

| 对象 | 约定 |
|---|---|
| Agent 构建 | `environment/Dockerfile`，context=`environment/`；只有公开资产和依赖 |
| Starter | `environment/starter/` 初始化只读 `/workspace/starter` 与可写 `/workspace/solution` |
| 每轮评分 | 公开只读 `public_eval` 或等价实现；当前本地组件生成 `/workspace/evaluate` 转发入口 |
| Verifier 构建 | `tests/Dockerfile`，context=`tests/`；自备依赖及授权私有资产 |
| 最终评分 | `bash /tests/test.sh`，从任意 cwd 读取移交候选，实际评分并可信写 reward |
| 移交 | 顶层 `artifacts=["/workspace/solution"]`；代码、必需模型/配置，非整个工作区 |
| 隔离 | Agent 不可见私有 tests；Verifier 内的候选也不能读私有标签/Reference 或改写 grader/reward |

`verifier.environment_mode="separate"`、两个环境资源小节均须存在。`schema_version` 采用项目指定 Harbor 的真实支持值，不把教程例子 1.3 写死为通用常量。评测依赖不能来自 Agent 临时安装或缓存。Hidden 可按授权私有预置、生成或安全注入；授权自验不称官方 Hidden 通过。

```bash
docker build -f "$TASK_ROOT/workspace/harbor_task/environment/Dockerfile" \
  -t task-agent:local "$TASK_ROOT/workspace/harbor_task/environment"
docker build -f "$TASK_ROOT/workspace/harbor_task/tests/Dockerfile" \
  -t task-verifier:local "$TASK_ROOT/workspace/harbor_task/tests"
python3 "$FLOW_ROOT/cli.py" environment check \
  --harbor-task "$TASK_ROOT/workspace/harbor_task"
```

`environment check` 只检查必要结构/TOML/明显 COPY 越界，返回 `structure_checked_not_execution`。它不是完整 Dockerfile 解释器，不证明权限、test.sh 实际评分或目标 Harbor 字段生效。

## 真实运行证据接口

实际命令必须与目标版本匹配。用户于 2026-09-30 暂定 Harbor 0.23；历史 pilot 使用 0.23.0 并核对其 separate、artifacts 和 Verifier 环境配置。此为本地暂定兼容目标，不是项目方正式指定。Compose/Buildx 仅安装到 pilot 专用 Docker 配置目录，不自动替换宿主环境；没有把本地 Docker 后端包装成 Harbor。先小规模打通 Agent→artifacts→separate Verifier，再接入正式运行监督；不需要为工具验证重跑双 10h。版本适用范围见 [发布说明](RELEASE.md)，设计历史只作维护追溯，不是执行依赖。

实跑后使用 [内部记录模板](templates/harbor-execution.example.json)，所有字段须据真实日志填写。此 JSON 是**通用流程内部检查接口**，不是教程额外指定的文件名或顶层目录。

- `task_sha256` 使用 `environment check` 输出，覆盖任务文件内容、目录和权限；更改会影响构建的内容后不得沿用旧证据。
- `harbor_version/provider/trial_id/command` 记录真实环境；镜像记录不可变 ID/digest。
- `data_authorization`、`reward`、各 observation 的 `evidence` 为 `{path,sha256}`；`locator` 指真实日志行/事件位置。程序检查存在、哈希和必要数值，专家核真实性，不接受一串无引用的 passed=true。
- 阶段 2.1 检查双构建、Agent 结束、移交、独立环境、依赖、候选权限和可信 reward。授权同接口数据可用于此时的最小执行链验证。
- 阶段 3.5 另要求 `frozen_scoring` 和实际冻结评分合同的 canonical SHA-256；4.1 核同一任务的有效实跑和双路预检。
- 最终检查另要求 `best_restored`、`best_method_sha256`、`candidate_manifest`。移交清单为 `{"root":"/workspace/solution","files":[{"path":"相对路径","sha256":"哈希","size_bytes":123}]}`，从**实际移交内容**记录，包含模型/配置；最佳代码每个文件必须与之匹配。清单不能由猜测生成。
- `score_contract_sha256`：阶段 3 对应 W2 冻结合同 JSON；最终对应 `expert_annotation.json` 的 `score_contract` 对象。二者字段表示不同，明确记录对应来源，不直接照搬哈希。

```bash
python3 "$FLOW_ROOT/cli.py" environment verify-record \
  --task-root "$TASK_ROOT" --harbor-task "$TASK_ROOT/workspace/harbor_task" \
  --file "$TASK_ROOT/evidence/harbor-execution.json" \
  --score-contract "$TASK_ROOT/evidence/score-contract.json"
```

最终模式再传 `--final --best-method /实际最佳代码目录`。CLI 在最终模式要求任务、最佳方法、receipt 和评分合同都在 `--task-root` 内；进行最终包检查时该根应指最终包。结果仍是 `evidence_checked_not_platform_approval`，不能冒称独立 QA 或平台通过。

## 稳定性（OP-2 可选诊断）与包内取证

政策修订 `2026-10-03.op02` 按用户通知 `U-20261003-03` 取消专门 12h 浸泡与收据门禁。新任务无需安排、等待或提交专门稳定性记录；未执行时阶段 6.5 记录 `stability={"status":"not_run","required":false}`，不能写成已通过。教程 AR-010 的 12h 目标仍保留，不改原文，也不据此豁免其他 QA 项。旧任务保留冻结政策，显式升级方式见 [OP-2 操作说明](OP02_STABILITY.md)。

[稳定性记录模板](templates/stability.example.json) 仅供确实做过的可选诊断或仍采用旧政策的任务使用。若要声明 12h 验证通过，仍须同一容器至少 43200 秒；开始/观察时间带时区，秒数与差值一致，无 OOM/意外退出，镜像须匹配已验证的 Agent 镜像。原始 Docker inspect/运行日志应能支持事实。真实迭代健康日志可复用，但不相加两轨时长，不把不足 12h 的运行换算为通过，也不把每次 Verifier 调用拉长到 12h。

可选只读诊断（不启动容器，不生成通过收据）：

```bash
python3 "$FLOW_ROOT/cli.py" --format json environment verify-stability \
  --task-root "$EVIDENCE_ROOT" --file "$EVIDENCE_ROOT/stability.json" \
  --agent-image 'sha256:实际已验证的Agent镜像标识'
```

`EVIDENCE_ROOT` 是记录内原始证据路径所相对的根；最终交付检查时为最终包根。模板中的空值和占位符不可作为证据。诊断失败不等于必须重新等待 12h，但其揭示的真实环境故障须修复并做有针对性的健康复核，不得隐去反证。

阶段 6.5 的 `harbor_execution` 必填，`stability` 在 OP-2 政策下可省略；两者若提交，引用仍相对题目根，文件须位于最终包内，记录内部原始证据引用则相对最终包。主动提供的 `stability` 会按上述严格标准校验，不接受失败/伪造记录或越界取证。原始 Harbor 日志、reward、候选清单仍须在包内。可用 `delivery build` 的 `support_files` 定点纳入必要材料，见 W4 文档。

取消此门禁不取消2.1真实环境/Harbor自验、4.1双路预检、工具可调用检查、运行中OOM/磁盘/FD异常处置。轨迹默认每条10h，OP-3合格非训练7h例外按 [时长政策](OP03_DURATION.md) 独立确认；故障时间仍扣除。已有真实稳定性证据不删除。

不规定额外安全框架。题目可采用合适的降权进程、只读固定面、可信恢复及平台隔离，但须实测候选无法读/写其禁止资产；不能在全私有权限 grader 进程 import 候选即声称隔离。

Harbor 0.23.0 实测注意：Harness 会在启动评分前重建并放宽 `/logs/verifier` 的权限。Dockerfile 中的 chmod 因而不足以证明 reward 可信；应在可信评分入口、执行候选前恢复适当权限或采取等价保护，并在真实 Harbor trial 中尝试候选越界写入。此为本地兼容实践，不是新增强制框架。

## v0.3.1 的静态 QA 与教程自验

H01–H04 必查；无 Job/Trial 配置时 H05 可不适用，无 Trial 时 H06 可不适用并写 runtime_status=not_run。已有材料必须复核，不能以不适用隐藏反证。NOP 是推荐自检，Oracle 非必交；有效候选 Trial 同样可作为运行证据。无 NOP 不单独失败，NOP 的零分也不单独决定链路是否正常。

以上是静态 Skill 的覆盖范围。最高优先级教程 L64、L539、L722、L912 仍要求真实构建和候选移交/独立评分自验，因此本流程保留 2.1、3.5、4.1、6.5 的真实证据门禁，不将静态 PASS 或 not_run 当作可交付。平台正式 Hidden 与本地授权自验须区分。

Hidden 准备方式可以是 prebuilt/generated/injected；须在专家说明写出材料来源、准备实现、调用入口和不可见边界，不强制目录叫 hidden_assets。提交包中的可见性清单按 [模板](templates/qa-exposure.example.json) 填写；最终镜像层和挂载须与实际 Agent 视图一致。奖励文件两者并存时优先 reward.json，评分前清理旧结果并原子替换。QA09 不额外强制 fsync/竞态全测，QA10 接受可信恢复、只读或校验保护的有效实现。
