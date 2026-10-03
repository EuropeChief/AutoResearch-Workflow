# CPU 运行底座联调夹具

这不是正式科学标注任务。仅可修改 `solution/method.py` 的 `order(values)`：返回整数列表的升序排列，不改变输入。允许任意正确排序算法，不允许修改评测入口、读取鉴权或访问目录边界外的数据。

调用唯一可信 Public/Dev 入口 `/workspace/task/evaluate`（预检允许 `--smoke`）。分数是六个固定公开用例的正确比例；原始指标是错误比例，越低越好。原始结果由评测器计算，不能伪造。用例为：`[]`、`[3,1,2]`、`[0,-3,0,4]`、`[9,8,7,6]`、`[1]`、`[-8,-1,-3]`。

每轮由你向 `/workspace/output/trajectory.jsonl` 追加 `round`、`method_summary`，并保存最佳源码到 `/workspace/output/best_method/method.py`。结果及方法摘要用中文，如实保留失败。不得访问 `/codex`、凭据、私有目录或宿主；不要尝试提升权限。只调用普通 shell、Python 和既定评测入口。
