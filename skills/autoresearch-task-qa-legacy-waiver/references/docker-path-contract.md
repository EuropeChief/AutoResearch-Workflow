# Docker 与运行路径契约

这是本项目采用的静态路径检查，静态通过不代表镜像已构建或平台适配已部署。部署能力先按[当前内场部署口径](innerfield-deployment.md)检查：默认MASO，预构建镜像，每sandbox必须单容器，不部署或调用额外工作环境，不用Compose；不同sandbox与separate要求不变。下文路径profile只确定来源与路径，不豁免内场限制。

当前默认 Agent 构建 context 为 `environment/`；选择专用 Verifier 构建时为 `tests/`。复用 Solver 镜像分支则在新的 Verifier sandbox 上传 tests。以下 task-root 路径为历史附件说明，不覆盖当前实际镜像选择与上传机制。

## 依据和真实附件缺口

已只读核对[专家教学文档](https://bytedance.larkoffice.com/docx/P1J5dgIw1oKchcxn29GcvzlMnSd)所附 `example.zip` 中 `workspace/harbor_task/environment/Dockerfile`、`task.toml`、`README.md`、`tests/test.sh` 与 `solution/solve.sh`。附件带 `example/` 外包装，可忽略该包装层。Dockerfile 实际包含：

```dockerfile
ENV EVFI_TASK_ROOT=/workspace
COPY environment/requirements.txt /tmp/requirements.txt
WORKDIR /workspace
COPY instruction.md task.toml ./
COPY environment/starter ./environment/starter
COPY environment/public_assets ./environment/public_assets
COPY solution ./solution
COPY tests ./tests
```

这些来源要求 **任务根目录**作为 build context；Dockerfile 放在 `environment/` 不代表 context 也在 `environment/`。这是历史教学示例的路径证据。当前要求不同 sandbox，可复用 Solver 镜像或采用专用 Verifier 镜像/构建；示例中的 `COPY tests ./tests` 会把隐藏集带入 Agent 镜像，不能沿用。

附件仅作为布局证据，有三项已知缺口：修改前教学 Agent 提示写 `TASK_ROOT=/harbor_task`，附件却用 `/workspace`；附件 TOML 使用自定义 `[task]/[resources]/[entrypoint]`，没有证明原生 Harbor 识别这些字段；附件 `tests/test.sh` 只执行 pytest，没有直接写 Harbor reward。2026-09-18教学正文已统一 `/workspace`，并补充平台字段映射与正式reward要求，附件本身未替换。不能把附件称为已经通过完整 Harbor 接口或平台构建验证的模板。

## 两种受支持 profile

下表路径均不包含 ZIP 外包装；`T` 是 `task.toml` 所在任务根。教学完整包推荐 `T=workspace/harbor_task`。直接送审独立任务目录时，`T=.`，目录职责与完整包结构另由格式检查判定。

| 项目 | `teaching-task-root-v1`（历史示例） | `harbor-environment-v1`（当前默认） |
|---|---|---|
| Agent Dockerfile | `T/environment/Dockerfile` | `T/environment/Dockerfile` |
| Agent build context | `T`，必须证明不会复制私有评分材料 | `T/environment` |
| Verifier Dockerfile / context | 专用构建为 `T/tests/Dockerfile` / `T/tests`；复用镜像则运行时上传，须有适配证据 | 专用构建为 `T/tests/Dockerfile` / `T/tests`；否则按原生镜像选择/上传机制 |
| COPY 来源 | 相对 `T`，例如 `environment/starter` | 相对 `T/environment`，例如 `starter` |
| 工作目录与任务根 | 最终 `WORKDIR /workspace`；声明的 `TASK_ROOT`/`*_TASK_ROOT` 与其一致 | 由实际镜像/版本明确指定，不能假设 `/workspace` |
| Agent 提交面 | `/workspace/solution` | 依据任务接口；原生 Oracle 的 `/solution` 不能直接当 Agent 可写工作区 |
| 测试入口 | 由适配器在独立 Verifier 镜像中提供 `/tests/test.sh` | 专用镜像预置或复用 Solver 镜像后上传至 `/tests/test.sh`；启动 cwd 不保证是 `/tests` |
| 源包入口 | `T/tests/test.sh`、`T/solution/solve.sh`；其他配置入口须真实存在 | `T/tests/test.sh`；`solution/solve.sh` 作为 Oracle 按需存在 |

历史教学 profile 的等价 Agent 构建命令（只用于描述，不由静态 QA 执行）：

```bash
docker build -f workspace/harbor_task/environment/Dockerfile workspace/harbor_task
```

禁止把 context 改成整个提交包后将 Reference、专家私有证据或最终私有评分材料复制给 Agent。公开 Dev 评分代码及数据必须保留供 Agent 使用，不能一概禁止“评分实现”或所有名为 tests 的文件。Verifier 必须具备正式入口、私有评测材料及独立依赖；Hidden 可用其他目录或有证据的生成/安全注入。禁止依赖专家本机绝对路径或 `../` 越出 context。构建命令、provider、COPY、WORKDIR、环境变量和入口必须形成一致路径链。

原生 profile 的依据见 [Harbor 规范](harbor-harness.md)，复核时说明目标版本。不能仅为规避路径错误改选 profile。教学布局须有真实适配证据，且不能暴露私有 tests 内容。必交一次当前题包版本的 NOP 自检记录，确认构建与运行链路可用；未提供时 H06 与 QA17 fail，运行状态记 not_run，原因写缺少记录。

## 自动检查与人工边界

默认 implementation 交付禁止 Compose（generic-harbor 也不豁免此文件交付规则）：在选定 task 根的 `environment/`（Agent）与 `tests/`（Verifier）直属位置发现 `docker-compose.yaml`、`docker-compose.yml`、`compose.yaml` 或 `compose.yml` 即 fail；与 Dockerfile 并存、预构建镜像、显式 docker_image 或 compose_review.selection=unused 均不豁免。自动扫描只覆盖这两个正式运行目录的直属文件，不递归扫描 docs、examples、history 或其他资料目录；非标准运行入口仍须人工核对，不得据未命中声称没有 Compose。详见[内场部署口径](innerfield-deployment.md)。

`scripts/docker_paths.py` 只读处理常见 Docker shell/JSON COPY 与 ADD、默认反斜线续行、WORKDIR、TASK_ROOT 环境变量、CMD/ENTRYPOINT 的显式脚本路径、简单 dockerignore，以及 TOML 中静态入口。按实际选中的镜像/构建定义解析；原生Harbor可用而内场不支持的Compose不能借profile绕过。需要Dockerfile的分支解析 Dockerfile；复用 Solver 环境时检查 tests 上传源和独立依赖，专用预构建镜像标内容待核实，检查各自 context 内来源、复制映射、忽略规则、越界链接和入口位置；Verifier 子结果及带 verifier_ 前缀的 findings 汇总到路径结论。Dockerfile 相邻的 `Dockerfile.dockerignore` 优先于 context 的 `.dockerignore`。

确定缺实际选中构建所需 Dockerfile/入口、混用 context、Agent 复制已识别私有 Hidden/Reference 材料、来源不存在、显式 WORKDIR/TASK_ROOT 错误、简单 ignore 排除必需来源、入口不存在、静态无法映射且没有生成步骤等，标 `fail`。H03 自动不通过，不能用手填 pass 或 `manual_resolution` 覆盖。

变量、远程 ADD、ADD 解包、多阶段及 COPY --from、路径相关扩展 flags、复杂 dockerignore、内嵌 shell、RUN 生成文件等不能完整解析时标 `manual`。不把阶段内来源当成本地文件，也不将“不支持解析”写成“平台一定构建失败”。须阅读调用链后补充真实证据。检查器不模拟镜像基础文件系统，不证明构建可达性、依赖安装成功、权限有效或任意 shell 命令正确；这些仍是 H03 的人工语义复核范围。

容器组织还须按 innerfield-deployment.md 沿实际启动和评分调用链做H03语义复核，区分平台准备、任务运行及外部请求用途。Dockerfile中的镜像构建步骤和文档中的Docker/SSH/HTTP词语本身不是违规证据；当前路径解析器与Compose文件扫描不自动识别所有额外工作环境。

## review 与输出字段

最终 `review.harbor.path_contract` 必须显式填写 profile 和来源，旧 review 不能默认冒充新契约已通过：

```json
{
  "profile": "harbor-environment-v1",
  "profile_basis": "目标 Harbor 版本的独立 Verifier 环境与实际镜像/构建契约"
}
```

可选 `dockerfile`、`build_context`、`runtime_task_root` 用来显式声明路径，前两种 profile 必须与计算结果一致（原生 profile 的 runtime task root 可按真实镜像声明）。`adapter_evidence` 是真实包内适配文件引用数组，不能只填口头声明。

仅对已标 manual 的动态解析项，可填写：

```json
{
  "manual_resolution": {
    "summary": "说明每个未解析项的最终路径和解析依据，最多 500 字。",
    "evidence": ["workspace/harbor_task/environment/Dockerfile:12", "workspace/harbor_task/build.sh:4"]
  }
}
```

字段是合并到同一个 `path_contract` 对象，并非另建 review。所有引用必须存在于送检包内。可采用 `custom` profile，但需填写三项路径和适配证据；它用于已有平台适配，不是任意忽略教学路径约束的豁免。无充分适配说明维持 manual。

`report.json.harbor.path_contract` 保存 `profile/profile_basis/sources/task_root/dockerfile/build_context/runtime_task_root/test_entry/observed_workdir/copy_operations/findings/status`，以及 Verifier 子结果、适配证据和人工复核说明。每条 finding 含 `code/status/message/evidence`。可复用 Solver 镜像或采用专用 Verifier 镜像。不一律要求双 Dockerfile；预构建镜像必须复核入口、Hidden、依赖与私有隔离。image_selection 保存真正的选择来源和 tests_delivery，不根据镜像相同与否猜测上传。任何路径 fail 都强制 H03 与 QA17 不通过；manual 无补充复核时 H03 不能通过。所有 profile 均不允许由静态结果声称动态构建成功。

退回建议示例：

> Agent 构建包含了私有测试材料。请将公开 Dev 部分提供给 Agent，并将最终私有评测仅交给独立 Verifier：专用构建可用 tests/ 上下文，复用 Solver 镜像则按目标版本运行时上传 tests；核对 /tests/test.sh、依赖、Hidden 的准备/调用与 Agent 产物移交。静态路径一致不代表已经完成镜像构建或评分运行。
