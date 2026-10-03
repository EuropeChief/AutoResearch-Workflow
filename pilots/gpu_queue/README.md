# 有界 GPU 队列探针（维护者）

用于流程发布的设备分配验证，不是每题步骤或科学结果。复用 `ExperimentRunner`：同一可信合成方法、相同3个seed，先串行后有限并行，各次只做一遍128×128矩阵乘法。检查实际 CUDA UUID、计算正确性、同卡不重叠、两组统计一致和完成后零重复启动。两卡时还须观测跨卡作业时间重叠；一张卡不能证明跨卡并行。

准备不查询 GPU、不导入 PyTorch；运行须另外显式 opt-in。用户先明确允许的1–2张卡及预算，授权原文放在文件中；最多6次独立适配器，每次30秒、合计最多180个适配器秒，无自动重试。忙卡返回等待，不抢占。不安装环境、不拉镜像、不修改其他进程；仅运行本仓可信的玩具方法，不在宿主运行 Agent 提交物。

从流程根执行，替换下列占位路径/卡号，使用新的label：

```bash
python3 pilots/gpu_queue/probe.py prepare gpu-check-new \
  --gpu-ids 4 6 --python-path /已有CUDA-PyTorch环境/bin/python \
  --approval /本次授权原文.md
python3 pilots/gpu_queue/probe.py run gpu-check-new --allow-gpu
```

Python须已有CUDA版PyTorch，且能读取 `torch.cuda.get_device_properties(0).uuid`（本机源码核对版本为2.6.0）；设备属性不满足时失败，不拿分配声明冒充实际设备。矩阵规模很小，预期总时间远低于上限。调用方仍需留出进程清理和记录开销，适配器超时上限不是费用或总墙钟硬限。

`runs/<label>/` 保存运行前源码快照、原样授权、冻结计划、队列原始请求/命令/设备/日志/结果和最终 `result.json`。准备拒绝覆盖；运行源码/计划漂移须查明。等待资源可用同一命令继续；方法失败或超时不自动换seed或重试。重复调用已完成探针只核原件，不重新计算。`serial-queue.json`/`parallel-queue.json` 是可刷新的汇总，逐次原件由队列保留。

`result.json` 可作为发布索引的 `gpu_dispatch.result`；真实验收还须审阅授权和原件，不能把离线模拟单测当GPU通过。发布工具不分发 `runs/`。本探针不验证 Harbor GPU provider、正式训练性能或共享卡独占，这些仍须逐题验证。
