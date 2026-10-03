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

## 当前实测（2026-10-04）

在明确授权的两张空闲 RTX 4090（GPU 1、2）完成 `runs/release-gpu-20261004b/` 六次真实 CUDA 运算；串/并行各3seed，原始值均为0、5、7。实际UUID与分配一致、同卡不重叠、跨卡作业时间重叠成立；完成队列再次检查未重复启动。

首次 `release-gpu-20261004a` 的三个尝试在UUID比较处失败：PyTorch返回裸UUID，NVIDIA分配使用`GPU-`前缀。保留原失败，补回归后仅规范化实际UUID（仍严格比较身份）；另获用户许可才重验。两次合计9个适配器进程墙钟约19.177秒，无训练，检查后两张卡无遗留进程。没有因此自动获得以后运行授权。

成功结果 `result.json` SHA-256：`fb1b63c888fad835a842691f6f7472549b8f69a853ade805dd14405ca51d99e0`。原件及源码快照本地保留，不随发行包分发；后续相关代码变更须重核适用性。
