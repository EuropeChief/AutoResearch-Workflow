# OP-0 / OP-1：冻结政策与题目 Git 管理

Git 功能初始修订：`2026-10-03.op01`；当前政策为 `2026-10-03.op03`，状态 schema 仍为1，流程版本仍为0.2.0。后续已实现的政策见 [稳定性政策](OP02_STABILITY.md)、[时长政策](OP03_DURATION.md)，不代表全部功能或新版迁移发布完成。

## 1. 已实现与尚未启用

已实现：七项用户通知与正式规则分层记录、任务政策快照、旧状态只读兼容、显式政策升级，以及新任务阶段 1.1 的 Git 范围确认和真实检查点。

OP-2 已取消专门12h收据门禁，OP-3 已支持经资格确认的非训练7h例外。尚未启用：TUI（OP-4）、并行调度（OP-5）、命令级QA后三包压缩（OP-6）和填表生成（OP-7）。`task policy`显示冻结政策和待实现项，不能手改状态提前开启。

`rules/catalog.json`的AR-038/044按教程表达7h例外，OP-3现已接入；默认仍每条10h、exec_json。例外必须在runtime准备前确认并冻结，不允许事后降低要求。OP-2按用户通知取消专门稳定性收据要求；不改教程，也不伪称已通过12h。

## 2. 政策结构与兼容

```bash
python3 "$FLOW_ROOT/cli.py" --format json task policy --task-root "$TASK_ROOT"
```

`workflow_policy` 保存 `schema_version`、`revision`、`git_required`、`duration_policy`、`ui_mode` 和 `require_stability_receipt`。它不保存鉴权，不替代模型 TOML，也不增加最终轨迹字段。

- 新初始化任务使用当前修订，`git_required=true`。
- 缺少该字段的旧任务按旧合同只读解释，默认 10h、`exec_json`，不追加强制 Git，不写回状态。
- 未实现的TUI或旧政策直接启用7h返回 `POLICY_NOT_IMPLEMENTED`；新政策的7h缺资格冻结返回 `DURATION_ASSESSMENT_REQUIRED`，未知schema/不一致字段返回 `INVALID_POLICY`。旧稳定性语义保留，须显式升级，不单改布尔字段。
- `duration_policy`由OP-3贯通默认36000秒与合格例外25200秒；资格、原始证据与实际运行快照共同核对，不只判断一个数值。

只有希望采用新政策的旧任务才显式执行：

```bash
python3 "$FLOW_ROOT/cli.py" --format json task upgrade --task-root "$TASK_ROOT" --adopt-policy
# 审查 affected_stages、来源变化与政策变化后，在已有授权内执行：
python3 "$FLOW_ROOT/cli.py" task upgrade --task-root "$TASK_ROOT" --adopt-policy --apply
```

不带 `--apply` 不修改文件；普通规则升级不自动采用新政策。采用 Git 新门禁会从阶段 1 重开受影响的已完成状态，原记录/实验文件不删除，仍匹配的科学证据可复用。已有 `.autoresearch-flow/runtime/` 时仍拒绝此类切换；不要删除运行记录绕过。仅从 OP-01 升级到 OP-02、只改变交付稳定性政策时允许已有 runtime，影响阶段为 6，不切换运行模式、不重开科学研究阶段。

七项通知记录在 catalog 的 `workflow_notices`，不冒充第三级正式权威或新增 AR 质检项；来源锁会保留通知快照。正式规则仍 50 条、质检覆盖仍 38 项，既有 QA 口头豁免不恢复。

## 3. 新任务：先确认仓库范围

`task init --confirm-init` 只初始化流程状态，不连带修改 Git 或身份。初始化后、阶段 1.1 判通过前执行：

```bash
python3 "$FLOW_ROOT/cli.py" --format json task git-status --task-root "$TASK_ROOT"
```

输出 `mode`：

- `new`：尚无 Git；建议仅在题目目录创建。
- `reuse_task`：题目本身已有仓库，复用它。
- `reuse_parent`：题目位于上层仓库；明确复用该根，但所有选中文件限定在本题路径下，不新建嵌套题目仓。

将上一步返回的 `repository_root` 填入以下参数；不要直接用共享工作区根代替：

```bash
python3 "$FLOW_ROOT/cli.py" task git-setup --task-root "$TASK_ROOT" \
  --repository-root <git-status返回的根路径> --confirm-git
```

此命令仅建立/复用所确认仓库、追加题目 `.gitignore`、保存专家侧绑定；不提交、不推送、不更改全局 Git 身份。原忽略规则保留，重复执行不重复添加同一块。

若缺身份，使用自己的实际身份在所确认仓库执行 `git -C <仓库根> config user.name ...` 和 `git -C <仓库根> config user.email ...`。工具不会替用户编造姓名、邮箱或设置全局值。

## 4. 审查清单后建立初始检查点

```bash
# . 表示预览整个本题，经过滤后列清单；不等于 git add -A。
python3 "$FLOW_ROOT/cli.py" --format json task git-preview --task-root "$TASK_ROOT" \
  --path . > "$TASK_ROOT/.autoresearch-flow/git-preview.json"
```

检查 JSON 的 `files`、`excluded`、仓库根、HEAD 和范围。也可用多个 `--path` 限定源码/文档目录。预览本身不更改 Git 暂存区；上述重定向文件在专家状态目录内，不纳入候选。

过滤凭据常见路径/文件、可识别密钥、数据/模型/日志/压缩包、内部运行目录、符号链接和单文件大于 10 MiB 的内容。10 MiB 只是本地 Git 便利阈值，不是项目提交限制。密钥检测是启发式，专家仍须审查清单；不能声称自动扫描能识别所有秘密。

嵌套官方代码仓整体排除，不清理其历史。若需跟踪它内部的科研改动，仍在该官方仓库按自身 Git 边界管理，并在本题设计/证据中引用版本；不要把专家 `.git` 打进 Agent 或最终包。实验源码快照的正式哈希仍由 W2/W4 绑定，不依赖 Git 代替。

确认清单后执行：

```bash
python3 "$FLOW_ROOT/cli.py" task git-checkpoint --task-root "$TASK_ROOT" \
  --file "$TASK_ROOT/.autoresearch-flow/git-preview.json" \
  --message "初始化题目来源与探索设计" --confirm-commit
python3 "$FLOW_ROOT/cli.py" --format json task git-status --task-root "$TASK_ROOT"
```

只有实际存在且可追溯的 commit 才返回 `ready=true`；空仓库不算就绪。此后仍须按原流程提供来源/输入证据，登记阶段 1.1，不因 Git 就绪自动通过科研判断。

检查点提交仅包含清单内路径：

- 无关路径已有的暂存和未暂存改动不进入本次 commit，也不被还原。
- 所选路径已有暂存内容时拒绝，防止覆盖部分暂存；先由专家处理后重做预览。
- 存在未结束的 merge/rebase/cherry-pick/revert/bisect 时拒绝建立检查点，不推进 HEAD，也不代用户清除操作标记。
- HEAD、内容、权限或清单在预览后改变时拒绝，需要重新审查。
- 已跟踪源码的删除会进入预览及检查点，不在快照中残留旧文件。
- 用独立 index 从已核验的原始字节与权限构建 commit tree，不让 `commit --only` 在提交时重读工作区；不执行 hooks、clean filter、换行转换或签名交互。不修改用户的 `core.filemode` 配置。
- Git 标准 `index.lock` 防止同时改写暂存；只更新所选路径在 index 中的条目，无关暂存完整保留；HEAD 使用比较后更新，发生并发分支变化则停止。
- 检查/提交失败不自动 reset 或删除用户文件。若底层 I/O 在更新 HEAD 与 index 的交界处失败，明确报错，需先检查实际 HEAD/index 再恢复，不记为成功。

## 5. 后续检查点与回退

建议在协议/评分冻结、正式 Agent 启动前、独立 QA 交接和最终交付时，用同样的“预览 → 审查 → 检查点”入口保存版本，不要求每轮粗筛都 commit。

`.autoresearch-flow/git_repository.json` 保留仓库相对位置、范围、检查点 commit、文件哈希及脏状态。它是专家侧过程记录，不是新增必交材料；同一仓库历史随任务整体搬迁时可继续定位，换仓或丢失 commit 则不能冒用旧就绪结论。

程序不提供自动 hard reset、清理、历史改写或远端发布。确需回退源码时先确定范围，保留实验日志与事实，再对受影响步骤执行 `stage reopen`。原始实验发生过的事实不能随 Git 回退消失。

## 6. 后续实现接续表

| 后续项 | 待替换/接入的位置 |
|---|---|
| OP-2 | `stages.py` 6.5 收据及模板、`pca_contract.py` 可选稳定性检查、环境文档 |
| OP-3 | `runtime.py` 运行/状态的 36000、`harbor_runtime.py` 收口、`w4_evidence.py` 时长审查、`w4_package.py` 摘要和例外检查、Prompt |
| OP-4 | `runtime.py` 的 JSON 进程监督、`harbor_runtime.py` PTY、日志与恢复适配；不丢原始证据 |
| OP-5 | W2 账本上的有限 GPU 队列，不重写统计协议 |
| OP-6/7 | 6.5 具名检查点 `qa_verified → archives_verified → form_ready`；archive 校验 QA 而非依赖 finish 6 |

这些位置已经登记，但本次不声称相应功能已启用。现有正式包、历史轨迹和发布证据不修改，迁移包的全量更新留给 OP-8。
