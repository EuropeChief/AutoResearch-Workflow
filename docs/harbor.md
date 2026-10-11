# 原生 Harbor 双镜像评分

输入是实际 `harbor_task/`、明确选定的候选目录和全新输出目录，不需要阶段账本。目标为已有 Harbor **0.23.0**、Docker/Compose 和题目两张镜像；Agent 镜像需有 Python。工具不安装宿主环境，不调用模型或选择方法。

## NOP 与候选各跑一条实际链路

在流程根使用已安装 Harbor 的 Python；若 Docker Compose 插件使用专门配置目录，先按本机设置 `DOCKER_CONFIG`。

```bash
python3 cli.py harbor run \
  --harbor-task /题目/harbor_task \
  --harbor-python /已安装Harbor的venv/bin/python \
  --output-dir /题目/验证/nop --allow-live

python3 cli.py harbor run \
  --harbor-task /题目/harbor_task \
  --harbor-python /已安装Harbor的venv/bin/python \
  --candidate /题目/最终候选 \
  --output-dir /题目/验证/candidate --allow-live
```

不传 candidate 使用原生 `nop`，保留镜像起点；这只证明 NOP 实际执行的分支，零分或负分本身不是链路失败。传 candidate 使用无模型适配器把冻结候选装入 Harbor 创建的 Agent 容器，**随后的 artifacts 移交、独立 Verifier 和 reward 回收仍由 Harbor 原生完成**。它不是新的 Agent 轨迹，也不代替同协议正式复验。

候选必须已经包含评分所需源码、模型和配置，可以直接引用独立 Codex 底座的已恢复 `runtime/solution/`。工具核完整文件哈希、大小与模式，不补造 checkpoint，也不从另一轨或 Reference 补取产物。若 Verifier 需要训练，仍按题包的固定协议执行；本工具不改变训练规则或 seed。

输出须与源题包、候选不嵌套，且不能已经存在。只快照实际题目入口、environment/tests/solution；不复制制作侧 runs/build。复制时跳过 Git/缓存、拒绝链接与明显凭据，不触碰专家研究 Git。镜像内部其他可见 Git、私有线索和可信评分权限仍需题目实现处理，不能把复制过滤当作全镜像安全证明。

目标 Harbor 的真实 schema 先校验；实际 Trial 再核 Agent/provider 覆盖、separate、Agent→Verifier 顺序、完整候选移交和原生 reward。构建路径复用 QA 的只读解析器，确定错误阻止启动；静态不能确认的镜像依赖由实际运行证明，其他 manual 事项仍按具体题目审阅，不自动宣称全部 QA 通过。Verifier 自带依赖和 `/tests/test.sh`，不能依赖制作侧远程服务。

## artifacts 路径

字符串声明 `artifacts=["/workspace/solution"]` 与对象声明都可使用。对象示例：

```toml
[[artifacts]]
source = "/workspace/solution"
destination = "solution"
```

`source` 是 Agent 容器的候选源路径；`destination` 是宿主 Trial 的 `artifacts/` 下相对路径，**不是 Verifier 的容器路径重映射**。上述例子的宿主落盘位置为 `<trial>/artifacts/solution`，Verifier 内仍为 `/workspace/solution`。嵌套 `destination="collected/solution"` 对应 `<trial>/artifacts/collected/solution`；只有省略或空字符串才使用默认 `<trial>/artifacts/workspace/solution`。

检查器读取与 Trial 绑定的冻结 `task.toml`，要求主服务（service 省略或为 `main`）的候选根声明唯一。显式目标缺失就失败，不回退默认目录、不寻找其他 `method.py`。非字符串、绝对路径、`..`、反斜杠、空目录名 `.`、保留的 manifest 路径及符号链接越界会被拒绝；原有候选源码/模型/配置哈希、大小、模式和 candidate_transfer 校验不变。报告中的 `artifact_path` 记录实际宿主相对目录，`artifact_contract_sha256` 绑定解析的 `task.toml`。

单次 Agent/Verifier 时限来自 task.toml。不把一组五 seed 复验强行限制为两小时。只有获准短验收才设 `--timeout-seconds`；它不是正式轨迹墙钟。每次命令只有一次 Trial，不自动重试或根据分数换 seed。`--allow-live` 表示本次明确执行，不能替代模型/算力/隐私等必要授权。

GPU 任务可按现有授权重复传 `--gpu-id 2` 等明确设备，复用薄 Docker provider 的设备/UUID/CUDA 检查与原生生命周期。每个非零 GPU 环境的数量须等于选定设备数；题包明确为 0 的阶段仍为 CPU、不分配设备。不同非零数量需先适配，不能偷偷削减资源。CPU 验收不证明 GPU 完整 Trial 已测。

## 查看与复用原件

输出保留题包/候选/程序快照、实际 Job 配置、Harbor 日志、原生 `jobs/score/<trial>/` 和自动核对结果 `report.json`。Harbor CLI 可能在 Trial 失败时仍退出 0；本工具检查原生 exception 和 reward，失败返回非零并保留原件，不写伪通过。

```bash
python3 cli.py harbor inspect --run-dir /题目/验证/candidate \
  --harbor-task /题目/harbor_task --candidate /题目/最终候选
```

inspect 只读核原件及冻结版本，不运行 Docker、模型或评分；当前题包/候选变了就指出不再对应。源码后来改动不自动重跑完好证据，但须审阅该改动是否影响已证分支，不能把旧版本原件冒称当前字节实测。失败原件用于诊断，不能作为成功 NOP/候选证据。

旧版检查器若仅因固定默认目录而误判，保留旧失败报告和冻结实现；用修复后的检查器读取原绑定题包及同一 Trial，另存检查器版本/哈希、输入哈希和复核结果，不改旧报告为通过。旧报告缺少原件绑定时，不能放松 `inspect` 的一致性检查来冒充历史通过。源码已修复、发行包已更新和历史记录已复核是不同状态；修复本身不要求重训或重做 Agent 轨迹。

最终材料可把需要的同一 Trial 原件映射到 `expert_evidence/nop_trial/`、`expert_evidence/candidate_trial/`，并在已有专家说明中绑定当前题包、镜像和原件版本。保留 config/result/reward/log 原字节与真实容器路径；包内取证路径用相对引用。不要把整个验证目录、流程程序快照、调试失败树或审批记录塞进最终运行包。见[材料组装](materials.md)。

评分器清理预写 reward、可信原子替换和候选隔离是**题目实现**的责任，本工具不会包装掉一个不安全 grader。对相关源码作定向审阅和必要负向检查即可；运行成功、JSON 可解析或本工具返回 verified 均不代替独立 QA。
