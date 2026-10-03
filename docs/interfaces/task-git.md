# 题目 Git 与冻结政策

Git 检查点用于审查和回退，不代替原始实验及正式方法哈希。新题初始化后、阶段 1.1 判通过前完成本节。

## 确认仓库范围

```bash
python3 "$FLOW_ROOT/cli.py" --format json task policy --task-root "$TASK_ROOT"
python3 "$FLOW_ROOT/cli.py" --format json task git-status --task-root "$TASK_ROOT"
```

`workflow_policy` 随新任务冻结，包含当前修订、Git、时长、原生 TUI 与可选稳定性策略；不保存鉴权或增加交付轨迹字段。只接受匹配修订的任务，不默补旧值。

`git-status` 返回 `mode` 和 `repository_root`：

- `new`：本题尚无仓库，只在确认的题目目录创建。
- `reuse_task`：复用题目现有仓库。
- `reuse_parent`：复用已有上层仓库，但文件范围限定于本题，不新建嵌套题目仓。

确认返回的根后执行，不用共享工作区根替代：

```bash
python3 "$FLOW_ROOT/cli.py" task git-setup --task-root "$TASK_ROOT" \
  --repository-root <git-status返回的根路径> --confirm-git
```

只建立/复用仓库、保留并追加题目忽略规则、保存绑定；不提交、不推送、不改全局身份。缺身份时由用户在该仓库配置真实 user.name/user.email，不编造身份。

## 预览并建立检查点

```bash
python3 "$FLOW_ROOT/cli.py" --format json task git-preview --task-root "$TASK_ROOT" \
  --path . > "$TASK_ROOT/.autoresearch-flow/git-preview.json"
```

审查 `files`、`excluded`、仓库根、HEAD 和范围；也可用多个 `--path` 只选择源码/说明目录。预览不改暂存区，`.` 不等于 `git add -A`。

程序过滤常见凭据、数据/模型/日志/压缩包、运行目录、符号链接和大于 10 MiB 的文件。此大小仅是 Git 便利阈值，不是提交包限制；密钥检测不保证穷尽，仍须检查清单。嵌套官方仓整体排除，其内科研改动在该仓跟踪并引用版本；专家 .git 不进入 Agent 视图或最终包。

```bash
python3 "$FLOW_ROOT/cli.py" task git-checkpoint --task-root "$TASK_ROOT" \
  --file "$TASK_ROOT/.autoresearch-flow/git-preview.json" \
  --message "初始化题目来源与探索设计" --confirm-commit
python3 "$FLOW_ROOT/cli.py" --format json task git-status --task-root "$TASK_ROOT"
```

只有真实、可追溯的 commit 才返回 `ready=true`，空仓不算。之后仍须登记来源与输入证据，Git 就绪不批准科研结论。

## 失败与后续使用

- 无关暂存/未暂存内容保留；所选路径已有暂存时拒绝，先处理后重做预览。
- 未完成的 merge/rebase 等操作、HEAD/内容/权限漂移或并发更新均须先核查；不自动清理操作标记或覆盖文件。
- 检查点绑定审阅过的字节和模式，包含已跟踪源码删除；不执行 hooks/clean filters，不改用户 Git 配置。
- 失败时检查实际 HEAD/index，不用 hard reset 或全目录覆盖代替修复。

协议/评分冻结、正式迭代启动前、QA 交接和最终交付时可用同一入口建立检查点，不要求每轮粗筛提交。内部 `.autoresearch-flow/git_repository.json` 不是新增必交材料；搬迁后须仍可定位同一历史，不能借丢失的 commit 声称就绪。

回退先确认范围并保留事实，再对最早受影响步骤执行 `stage reopen`。Git 回退不删除已发生的实验或日志。时长选择见 [时长接口](duration.md)，环境诊断见 [环境接口](environment.md)。
