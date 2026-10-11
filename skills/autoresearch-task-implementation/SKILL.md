---
name: autoresearch-task-implementation
description: 将 AutoResearch 研究方向实现为题面、公开开发环境、候选接口及独立 Verifier，或修复其调用与可见性。用于环境构建和接入返修，不代替科学标定或最终独立 QA。
---

# 任务实现

输入是实际研究方向、允许面/固定面、数据和资源、现有代码及目标 Harbor 版本。先定位要实现或修复的调用链，不为局部改动重建整套环境。

阶段 2 入口、`task_ready` 前及退出按[阶段预检](../../docs/preflight.md)核当前实现与前置证据；评分/可见性/路径有影响性变化时只复核关联项。局部返修不补办无关阶段，实跑仍须本次资源授权。

新题正式实现沿用已确认的 `research_contract`；没有确认可先准备与探查，不默认为专家已批准。阶段 2 本身不新增审批。会实质改变优化面或研究范围时回到该决定，普通代码修正不重复申请。

1. 写实质完整的英文八章节题面，明确目标、真实输入输出、评价、可改面、边界、提交物、迭代与完成条件。随机任务把 seed 和有效提升阈值写到题面，不能只在私有协议写 3σ；明确网络与工具政策。见[题面与格式](../../rules/README.md#c03)和[提交内容](../../rules/README.md#m12)。设计疑难可参考 [task-authoring](../autoresearch-task-authoring/SKILL.md)。
2. 实现真实方法接口与合理起点，确保合法算法改动能进入执行路径。公开 Dev 供 Agent 反复调用；固定部分按实际要求保护。只实现需要的隔离，不默认每题引入 Broker、chroot 或多进程服务。见[可见性](../../rules/README.md#m05)、[硬约束](../../rules/README.md#m06)。
3. 分别构建 Agent 与 Verifier 环境，显式 separate。核 context/COPY/依赖/权限、实际候选及模型的绝对路径移交；不得把完整作者包挂载给 Agent。见[双镜像路径](../../rules/README.md#c05)。
4. 沿 `/tests/test.sh` 的真实调用落实指标、分类失败与 reward，清除预写结果并可信原子替换。见[评分出口](../../rules/README.md#c04)、[结果防伪](../../rules/README.md#c01)。存在 Agent 可见 Git 时处理[答案线索](../../rules/README.md#c02)，不删除专家研究仓库。
5. 在已有资源授权内验证实际公开反馈和有效候选评分链路，保留当前版本的原生 NOP Trial；不能以 pytest、手工 Docker 或早退 NOP 证明全部候选分支。目标版本配置与调用核[Harbor 要求](../../rules/README.md#m07)、[运行配置](../../rules/README.md#c06)。模型/GPU 调用无授权或环境不足时先处理具体阻塞，不冒充已实跑。

需要 NOP 或明确候选的实际 Trial 时使用[原生 Harbor 接口](../../docs/harbor.md)，以实际题包/候选为输入，不初始化旧阶段状态。只读 inspect 可复用仍对应当前题包的原件。

产物是能运行的 `harbor_task/`、专家侧 `reference/` 和必要调用/隔离证据。B/R 实际运行、代表性及评分锚点交给[实验能力](../autoresearch-experiment-validation/SKILL.md)。代码改了哪里就核相关路径；无关训练和证明不自动重跑，不额外生成逐条约束签字表或全套攻击报告。
