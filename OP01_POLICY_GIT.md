# 冻结政策与题目 Git 管理

任务政策随新任务冻结，Git 检查点支撑版本审查和回退；不以 Git 代替原始实验或科学证据。

## 政策结构

```bash
python3 "$FLOW_ROOT/cli.py" --format json task policy --task-root "$TASK_ROOT"
```

`workflow_policy` 保存 schema、修订号、Git 要求、时长、运行模式和稳定性收据策略，不保存鉴权，不增加最终轨迹字段。当前修订为 `2026-10-03.public`，任务 schema 为 2。

新任务要求 Git 检查点；默认每轨 10h、当前运行模式为 exec_json、专门稳定性收据可选。合格非训练 7h 例外须启动前评估并冻结，见 [时长政策](OP03_DURATION.md)；诊断边界见 [稳定性](OP02_STABILITY.md)。TUI 等尚未启用能力由 `task policy` 明确报告，不能手改状态开启。

当前只支持新任务和同版本恢复。缺少政策或旧修订不默认补值，旧状态只读拒绝并使用原版本处理，不提供升级命令。规则中的原始用户通知、当前执行政策和工程实现状态分别记录，不把“已批准”视为“已实现”。

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
