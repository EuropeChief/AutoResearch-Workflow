# 原标准完整保留核对表

基准：用户提交的review_skill-0.3.10_1015(1).zip，SHA256=dfb5a3e46e44b91df1c777f829d88c1d0074f0ca48e4fd4718698a2cdb8236ce。

原SKILL正文、全部原references与scripts保留。新增的仅是适用说明、豁免与最终包装层；原标准结论不会被回写成通过。本表是核对导航，不取代原文细则。

| 原标准内容 | 完整保留的位置/原检查链 | 本包处理 |
| --- | --- | --- |
| 原工作流程、先读规范、只读边界、输入清点、四份报告 | SKILL原正文；audit_task.py→implementation_review.py | 原静态阶段实际执行并保留原报告；豁免报告是追加最终层。 |
| G01方法级优化面、G02健康公平Baseline五维、G03真实提升 | research-quality.md、content_gates.py、Baseline专项 | 原门槛/原值与复算均保留；历史换卡/新环境复验仅按具体原因免，不洗原科学失败。 |
| QA01–QA21逐项语义 | implementation-policy.md、implementation_review.py | 每项原判/证据/子发现保留；豁免不删除或合并检查。 |
| Docker路径、镜像、依赖、公开Dev与私有Hidden、artifacts移交 | docker-path-contract.md、docker_paths.py、harbor_review.py | 实际采用分支逐项检查；平台运行证明缺口不覆盖已确认的当前静态错误。 |
| H01–H05、provider/profile、配置覆盖、单容器/Compose、reward | harbor-harness.md、innerfield-deployment.md、harbor_review.py、deployment_review.py | 原配置/路径/Hidden/移交与部署详细对象保留，不能只看F七项。 |
| **H06 NOP及QA17派生** | **harbor-harness.md，harbor_review.validate_trial_evidence** | **原校验实际执行；有记录必读，缺记录原fail/not_run，再对获准旧题缺口豁免。** |
| QA15有据完整单轮资源估算、阶段/实测推断、7200秒/8张H20或L20/64CPU、CPU不加GPU | runtime-integrity.md、resource_review.py | 原estimate、硬件和已有反证结构保留；历史硬件差异与当前明确超限分开。 |
| QA16各轨有效时长、扣除、10h及7h例外、方法闭环/best复验 | implementation-report.md、content_gates.assess_runtime（由implementation_review调用） | 原有效时长观察与判定保留；历史缺口不改成已达标，也不自动补跑。 |
| QA18实际模型/runtime/推理档位、同Prompt/任务/Dev/资源和独立空输出 | runtime-integrity.md、trajectory_review.py及人工语义底稿 | 允许模型组合变化；两轨独立与同条件可比分开，保留.4.1实质条件比较。 |
| QA18每轨行为/分数、valid/invalid/unverified、已交sources与sessions审阅、自动candidate观察闭环 | runtime-integrity.md、trajectory_review.py | 原观察及人工解释保留；关键词不直接判作弊，也不能忽略已交反证。 |
| 泄漏/作弊/infra影响作者正式B/R | trajectory_review与implementation_review联动 | 受影响原成绩与路径保留；无效值不能经豁免作为G03改善正证。 |
| QA21原八字段、JSON/JSONL与四项题包指纹 | submission_format.py、task_fingerprint.py、implementation_review.py | 先记录实际schema/指纹观察，再按旧字段/迁移原因豁免；不能跳过读取与计算。 |
| 原标准检查未完成或工具错误 | 原阶段报告与inspection_error | 由质检方处理，不能用另一份手填pass掩盖后直接放行，也不自动转成专家补跑。 |

## NOP逐项核对

同次Trial的config.json、result.json、reward.json或reward.txt、trial.log或test-stdout.txt；两处agent身份一致且nop；separate；已有sandbox ID相同为反证；有finished_at、无exception_info；reward.json优先、非空有限数值并与verifier_result.rewards一致；日志非空；现有配置/日志/专家说明支持题包版本关联。0分不是自动失败，实际缺提交早退只能说明该分支。

原标准只读核查已有NOP，不自动发起NOP。缺失/不完整/异常的原始事实保留，豁免只改变获准历史问题的本轮处置，不能把错误reward、Oracle Trial或异常日志说成NOP成功。
