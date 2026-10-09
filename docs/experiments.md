# 独立实验运行与统计

适用于探索、Baseline/Reference 标定与最终最佳方法复验。直接提供真实方法、协议和输出位置；不需要任务初始化、流程账本、`selection.json` 或阶段审批。已有结果只统计，不自动重跑。

## 运行

```bash
python3 /流程根/cli.py --format json experiment run \
  --method /题目根/method --protocol /题目根/protocol.json \
  --role baseline --output-dir /题目根/runs/baseline \
  -- python3 main.py --seed '{seed}' --result '{result}'
```

`--method` 是实际源码/配置文件或目录，不是含数据、模型、凭据的整个工作区。工具复制方法快照，命令在快照中执行；依赖、数据路径和真实训练/评测入口由题目提供。命令必须前台执行并等待子作业结束，不能只提交后台作业就退出。此工具不是候选代码沙箱，也不替代 Harbor 正式评分链路。

可选项：

- `--jobs 2 --gpu 4 --gpu 6`：只使用已授权的指定卡，启动前简单核查是否有计算进程；无空闲卡且无本组在跑作业时返回待运行 seed，不长期等待。`--gpus-per-run` 默认 1；不传 GPU 则给子进程空 `CUDA_VISIBLE_DEVICES`。
- `--cpu-threads N`：设置 OMP/MKL 线程数；没有参数时保留运行环境。并行须不影响单次协议，尤其注意性能指标、CPU 和数据带宽竞争。空闲检查不是跨用户资源预留或强隔离。
- `--timeout-seconds N`：可选的单次作业超时，没有统一整组两小时限制。
- `--resume`：其余输入保持一致，核验并跳过已有成功项，失败项新建 attempt；方法、协议或已完成证据变化则拒绝复用。旧尝试保留。改变方法或协议请使用新输出目录，不在同一组混合结果。

命令参数可用 `{seed}`、`{method}`、`{output_dir}`、`{result}`、`{request}`、`{protocol}`、`{devices}`。同样提供 `AUTORESEARCH_SEED`、`AUTORESEARCH_OUTPUT_DIR`、`AUTORESEARCH_RESULT`、`AUTORESEARCH_PROTOCOL` 环境变量；`{result}`/`AUTORESEARCH_RESULT` 是本次原始 `measurement.json` 的写入位置。程序自动记录实际命令、退出码、时间、设备和 stdout/stderr，无需人工抄录。

## 协议与测量输出

协议是题目真实约定，不是审批文件。最小示例（数值与 seed 仅演示）：

```json
{
  "metric": {"name": "error_percent", "direction": "minimize", "unit": "%"},
  "split": "public_dev",
  "data": {"version": "实际版本或文件指纹", "split_definition": "实际划分"},
  "training": false,
  "evaluation_mode": "random",
  "purpose": "formal",
  "seeds": [1, 2, 3, 4, 5],
  "budget": {"evaluations": {"mode": "exact", "value": 1, "unit": "run"}}
}
```

把模型/数据/增广/预算等不变条件记入该协议；Baseline 与 Reference 使用完全相同协议。`evaluation_mode=deterministic` 需要 `determinism_basis`，不能从固定 seed 或偶然相同结果推断确定性。探索可用少量 seed 并设 `purpose=exploratory`；正式最低重复数按当前规则判定，高方差用 `high_variance=true`。数值预算支持 `exact` 或 `maximum`，由实际值核对；描述性预算仍需专家读日志核查。

题目入口完成后写原始测量：

```json
{
  "status": "SUCCESS",
  "seed": 1,
  "metrics": {"raw": 4.5},
  "quality_gate": {"passed": true},
  "actual_budget": {"evaluations": 1},
  "artifacts": {}
}
```

`seed` 如提供必须等于本次 seed；`metrics.raw` 是原始值，不是归一化 score。退出成功不替代质量门通过；失败、非有限指标、预算不符或缺必要证据会记为无效。入口必须真实使用 seed，不能只把数字写进文件。

训练型设置 `training=true`，每次独立训练并保存模型，再由题目入口在干净进程实际重载验证，额外输出：

```json
{
  "training": {
    "origin": "initialization",
    "model_format": "实际格式",
    "reload": {"passed": true, "raw_metric": 4.5}
  },
  "artifacts": {"model": "model/weights.pt", "reload_log": "model/reload.log"}
}
```

这里是合并到测量对象的字段，不是替代整个测量。路径相对于本次 `{output_dir}`。共享预训练使用 `origin=declared_pretrained`，并在协议中声明 `pretrained`；重载容差可设 `reload_tolerance`（默认 0）。工具按实际模型生成 `artifact.json` 和哈希绑定，检查重载指标/日志是否齐全，但不替题目实现训练、重载或认证日志真实性。

## 统计已有结果

```bash
python3 /流程根/cli.py --format json experiment summarize \
  --results /题目根/runs/baseline /题目根/runs/reference \
  --output-dir /题目根/comparison
```

接受显式结果文件或直接含 `seed_*/result.json` 的目录，不递归混入重试记录。可选 `--protocol` 提供旧证据未嵌入的实际协议，`--evidence-root` 指定旧证据相对路径基准。缺绑定的旧结果仍可得临时统计，但明确标为证据不全，不能补写假运行记录。支持 `metrics.raw`、`metrics.raw_metric`、`raw_metric` 以及历史 `metrics.value`/`metrics.primary.value`；指标名和方向须一致，不会拿 `score` 冒充原始指标。

旧协议字段布局不同时，可在提供的协议中用 `source_protocol` 原样保留旧协议对象。每份原件必须与该对象严格相同才允许按新字段复算；结果始终注明旧格式语义待核查，不自动转成正式通过，也不修改原件。没有通用映射的特殊格式需要只读适配，不要求重做原实验。

输出均值、样本标准差（n−1）、完整声明 seed 的配对改善和 3σ 数值判定；单样本标准差为 null，不取两侧 seed 交集挑选。没有 U 也能统计。若已有独立论证的 U，可提供 `--score-contract /题目根/score.json`，内容为 `{"upper_bound": 3.0, "rationale": "实际独立依据"}`；工具据 B 均值计算不裁剪分数并提示 Reference 区间，不自动估 U，也不裁定其论证有效。

`COMPLETE`/退出码 0 只表示本次声明结果与结构性证据完整。还须看 `formal_sample_complete` 和显著性字段；不够正式样本时仍保留探索统计，不能宣称科学通过。失败/缺项返回 `PARTIAL`/退出码 2；输入错误也返回非零。Baseline 代表性、优化面、Reference 未饱和及 U 依据仍由专家审查。

## 输出与接续

```text
runs/baseline/
  experiment.json                 自动输入指纹，非手填账本
  protocol.json
  seed_1/result.json               当前尝试的逐次结果
  seed_1/attempt_001/
    method/  request.json  run.log  measurement.json  result.json
    model/                        仅训练型；实际模型、重载日志和元信息
```

成功/失败均保留原始尝试；中断后不假定成功，退出信息无法恢复时明确记缺失原因。仅同一输出目录有防重复启动锁，不耦合其他组。统计可选生成 `comparison_summary.json` 与 `summary.md`，默认不覆盖已有报告。

这些是工作侧实验产物，不要求把指纹、锁、全部重试和调度记录搬入最终包。交付时按[证据要求](../rules/README.md#m11)选择必要原件并调整包内引用；材料装配由后续独立工具负责。接口只做执行与统计，不自动冻结方法、触发 QA 或打包。
