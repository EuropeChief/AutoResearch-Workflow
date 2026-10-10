# 独立 QA 后直接打包

指定最终包、独立 QA 终稿和包外附件目录即可，不初始化任务，不登记阶段或 qa-bind。给定新目录时直接使用；目录已存在时自动创建唯一的新结果子目录，不覆盖旧附件：

```bash
python3 /流程根/cli.py --format json package \
  --package-root /题目根/submission \
  --qa-report /独立质检/report.json \
  --output-dir /题目根/deliverables/本次附件 \
  --name method-research
```

三份 ZIP 均取自这个包：完整提交包、workspace/harbor_task、optimization_evidence。完整包外层用指定名称，子仓以 harbor_task、optimization_evidence 为根。默认不添加题号，可显式改名；拒绝路径穿越或与子仓重名。

## QA 与版本对应

读取当前项目方 schema 4 的完整 PASS；G/QA/H 适用项、NOP、运行及格式复核须完成。允许的不适用和一般风险提示不升级为失败，收集器初稿不能打包。

目录报告默认复用已有 inventory.json、实际扫描路径和生成时间：核文件清单以及内容/权限的后续改动。QA 扫描副本仍在时，直接比相对路径、内容和权限。没有要求新增绑定台账。

已有明确算法的版本摘要也可复用：支持 source.package_digest 中 algorithm=sha256-canonical-package-snapshot-v1、value=原 package_snapshot 规范 JSON 的 SHA-256。不同/未知摘要算法不互换。QA 扫描 ZIP 时核 source.sha256 并流式比较原 ZIP 的文件内容、已记录权限与当前包，不执行解压内容；普通 ZIP 允许隐式目录，未记录的目录权限不声称已核。新输出 ZIP 则保存全部目录及权限。

目录报告通常没有原始内容哈希；清单和文件系统改动记录适用于普通工作核对，**不是取证鉴真**，不保证识别伪造时间、底层时间粒度内改动或被替换的历史。若依据不足/不可信，需核已有实际版本依据或重新独立审对应包，不能宣称原报告有未记录的哈希。原扫描目录丢失且无明确摘要时，工具只指出这个缺口，不自动运行 QA。

源包至少具备 workspace/{harbor_task,reference}、expert_evidence、optimization_evidence。输出不得在包内或覆盖旧目录；源包/报告在压缩期间改变则停止，不留下成功附件目录。工具不重跑材料全检、科研审查、训练、模型重载、NOP、双轨或 12h 检查；报告真实性和独立会话属性仍靠实际来源保证。

## 大附件

默认上限 300,000,000 字节，超限才分卷，默认每卷 min(290,000,000, 上限) 字节。--upload-limit-bytes 和 --part-bytes 可按提交系统调整，没有永久 300 MB 上限。

程序流式读回核 CRC、清单、内容和 Unix 权限，中文名使用 UTF-8；分卷拼接哈希须与完整 ZIP 相同。完整 ZIP 留本地：未超限上传 ZIP，超限只上传全部 .part001、.part002…。

分卷为字节切片，单卷不能解压。收齐后按“上传说明.md”的明确顺序合并，再用 SHA256SUMS.txt 核传输完整性。工具不会自动上传。

## 七项填表

附件目录自动生成“填表信息.md”：研究子方向、优化面介绍、Baseline 描述/分数、Reference 描述/分数、小规模试跑结论。分数来自当前包正式汇总及 annotation，标原始指标、方向、split、seed 和归一化值；明确数值矛盾会停止，不能以 Agent 最佳值替代 Reference。

文字取专家说明的同名 Markdown 标题，或可直接复用的 annotation/QA 方法介绍（教程的 research_direction 原文可直接复用，不推断更细子类）；不足时可通过 --form-notes /题目根/简短概述.md 提供普通 Markdown：

```text
## 研究子方向
实际子方向
## 优化面介绍
实际允许的方法改动
## Baseline 描述
正式朴素对照
## Reference 描述
正式参考方法与差别
## 小规模试跑结论
从双轨前期真实记录总结，不虚称另做过独立试跑。
```

备注不需 sources、checks、签名 JSON，不能覆盖结构化分数。文字由制作 Agent 据实核对；未找到资料就标待补，不自动调用模型或编结论。

form.status=pending 表示“压缩完成，填表待补”，不阻塞合格包压缩，也不宣称全部交付齐全。工具不生成 archives.json、form.json、QA 绑定指针或阶段记录，不写入源包；源包未变的压缩与包外表单修订不需重训或重做 QA。
