# 新环境部署与开始新题

先部署通用流程及中央规则一次，再为每道题指定独立任务目录。规则不需要放到题目目录中。

当前 0.2.0 PCA 版已发布，迁移包及解包复验记录位于中央根 `deliverables/`。旧 0.1.0 包仍对应 v4，不覆盖或静默升级。用户暂定 Harbor 0.23.0 为本地兼容目标，非项目方指定版本；其他版本/provider 不视为自动兼容。

## 一次性部署

在任意可写的中央目录下保留下列相对布局（顶层路径可变，下面这些目录名不能随意改）：

```text
中央根/
  AutoResearch新流程/             # 此流程包：代码、文档、模板、模型 TOML、薄 Skill、测试
  AutoResearch新流程设计/         # W0 锁定资料及实施/验收说明
  通用规则/
    AutoResearch 专家线下标注教程｜PCA 双镜像对齐版/
      AutoResearch 专家线下标注教程｜PCA 双镜像对齐版.md
  .codex/skills/
    autoresearch-task-qa/         # 原样保留项目方 Skill 包
    autoresearch-baseline-quality/
```

源码和锁定依赖详见 [清单](release/source_manifest.json)；这不是压缩包复制命令，也不包含所有 QA Skill 执行脚本，部署时上述两个项目方 Skill 文件夹应完整复制。验收证据可保留 `release/` 的小型报告；**不要复制** `pilots/` 下任意 `build/`、`runs/`、`__pycache__/`、旧题目录、旧根 `config.toml` 或密钥。pilot 运行原证据只在发布工作区留存，不是每次部署的运行依赖。

前置条件：Python 3.11+；运行 Agent 时还需 Linux、用户可直接访问 Docker、任务镜像内的固定 Codex 版本及任务依赖；GPU 仅在题目需要时配置。

Harbor 0.23.0 单独安装到 Python 3.12+ 的虚拟环境，不要求流程核心与它共用 Python。本地试验使用 Python 3.13。准备 Docker Compose/Buildx 插件，在题目 runtime 配置中指定 `harness.executable`，需要专用插件目录时再填写 `harness.docker_config`。迁移时重新填写本机路径、构建/拉取对应镜像并预检；不要复制本机虚拟环境或照搬本机镜像 ID。CPU 短测不证明 GPU 分配已在新机器验证。

分别检查 `model_profiles/codex.toml`、`model_profiles/seed.toml` 中的模型、地址和鉴权**路径引用**。将鉴权文件另行安全配置到当前机器，只填 `auth_ref.path`，不把密钥粘入 TOML、Prompt 或任务状态。原文件中的绝对路径属于本机配置，不应假设在新机器存在。当前模型参数可沿用，但仍需核对新题当期模型/推理档位要求。

```bash
python3 /中央根/AutoResearch新流程/cli.py --format json version
python3 /中央根/AutoResearch新流程/cli.py --format json rules check
```

来源缺失或哈希不符时先补齐原件/审查版本变化，不手工改哈希使检查通过。只迁移目录不改变原件时，无需重做 W0 提炼。

## 开始新题

创建独立题目目录，放入题目卡、论文、代码或明确获取链接。向专家 Agent 提供如下指令（Codex 或 Pi 均可）：

> 请使用 `/中央根/AutoResearch新流程/START_HERE.md` 指定的新流程处理 `/题目根`。我授权为该新题初始化状态。先核对中央规则，按六阶段推进；涉及高成本运行与冻结时按流程确认，不迁移或引用其他题目的状态。

也可以让宿主直接读取本包 `skills/autoresearch-workflow/SKILL.md`。安装薄 Skill 只是方便发现入口，不改变流程行为；本轮不自动安装或覆盖宿主 Skill。旧仓库 `AGENTS.md` 可能仍指向旧流程，所以开始新题时需**明确选择此新入口**，不能混用两套状态。

之后按照 [START_HERE.md](START_HERE.md) 恢复当前步骤。每题只做题目适配、相关实验和两路真实 Public/Dev 预检；无需复制通用程序、重建 Broker 或重跑全套发布测试。更换机器、Codex 版本或安全边界时，针对变化补测；某台机器的安全例外不可直接继承。
