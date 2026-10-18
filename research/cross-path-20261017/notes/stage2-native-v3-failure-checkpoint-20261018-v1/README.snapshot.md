# AxVisor跨路径干扰研究文档

本目录以[《论文提要》V3.0](论文提要.md)为研究依据，优先完成阶段0～2。先从[研究进度](研究进度.md)了解当前结论和待办，再按本页查找设计、正式报告、复现入口和原始证据。研究进度持续更新；带封存哈希的旧报告保留当时结论，不作为当前状态页。

## 1. 研究目标与结论

研究围绕关键实时Guest与Linux干扰Guest，测量中断压力A、内存压力B及其组合对端到端实时性的影响。阶段2先判断交互是否稳定，阶段3才解释机制；机制成立后才实现联合优化。

### 1.1 当前阅读入口

以下文件分别负责范围、状态和验收，避免从历史日志推断当前完成度。

| 内容 | 入口 |
| --- | --- |
| 研究问题、六阶段计划与M1/M2/M3 | [论文提要](论文提要.md) |
| 当前结果、运行队列、剩余工作 | [研究进度](研究进度.md) |
| 原协议阶段0～1及M1的正式验收 | [可观测性验收](tgoskits/research/cross-path-20261017/results/phase01-final-acceptance.md) |
| 原四组均值交互、尾延迟、DMR和Linux吞吐 | [四组正式报告](tgoskits/research/cross-path-20261017/results/factorial-report.md) |
| 96次强度批次已交付 | [强度报告](tgoskits/research/cross-path-20261017/results/intensity-v3-report.md)、[最终交付](tgoskits/research/cross-path-20261017/results/intensity-v3-final-delivery.json)、[新封存](tgoskits/research/cross-path-20261017/SHA256SUMS.intensity-v3-v1)；完整冷重放及Spec→Quality已通过 |

原正式条件未观察到稳定均值交互；这不意味着所有工作负载都不存在耦合。新增强度与相位条件的完成度以当前进度页为准，不能由原四组报告替代。

### 1.2 指标与解释边界

交互项使用同一指标的运行级均值：`I_AB = mean(L_AB) - mean(L_A) - mean(L_B) + mean(L_0)`，并按完整实验区组报告不确定性。尾部分位数、截止期违约率及最大观测延迟单独呈现，分位数非加性不作为耦合证明。

T0为Hypervisor可见的软件边界，T4为软件Entry，T6为任务线程完成。校时、阶段重叠和关联分母见[阶段契约](tgoskits/research/cross-path-20261017/design/current-stage-contract.md)及[正式关联审计](tgoskits/research/cross-path-20261017/results/factorial-final-stage-association-report.md)。最大观测时延不称严格WCET/WCRT；QEMU只提供功能证据，Cache/内存干扰结论依赖真板。

## 2. 阶段0～2的实验与复现

正式材料均在 `tgoskits/research/cross-path-20261017/` 内。`design/`保存设计和预登记计划，`configs/`保存输入，`raw/`保存实际输出与工件，`results/`保存审计及统计，`patches/`保存可审阅增量。

### 2.1 已完成的原协议

下列入口覆盖原双VM测量和原四组数据。报告与源码版本成套使用，不能把新相位协议的开销或功能状态回填到旧版本。

| 内容 | 设计、结果或工具 |
| --- | --- |
| 双VM、CPU拓扑与回收 | [输入设计](tgoskits/research/cross-path-20261017/design/dual-vm-inputs-and-interaction.md)、[真板拓扑验证](tgoskits/research/cross-path-20261017/results/topology-native-v3-report.md) |
| 中断压力A、内存压力B | [IRQ压力设计](tgoskits/research/cross-path-20261017/design/irq-pressure.md)、[内存压力设计](tgoskits/research/cross-path-20261017/design/linux-memory-pressure.md)、[实际压力暴露](tgoskits/research/cross-path-20261017/results/factorial-pressure-exposure-report.md) |
| 追踪开关与探针范围 | [记录操作报告](tgoskits/research/cross-path-20261017/results/recorder-ops-report.md)、[开销口径](tgoskits/research/cross-path-20261017/design/current-probe-cost-plan.md) |
| 阶段分解与关联歧义 | [基线阶段报告](tgoskits/research/cross-path-20261017/results/stage-baseline-report.md)、[正式关联审计](tgoskits/research/cross-path-20261017/results/factorial-final-stage-association-report.md) |
| 原四组输入、均值和端点 | [固定计划](tgoskits/research/cross-path-20261017/configs/factorial-recovery-plan.json)、[运行均值CSV](tgoskits/research/cross-path-20261017/results/factorial-run-means.csv)、[任务端点CSV](tgoskits/research/cross-path-20261017/results/factorial-task-endpoints.csv) |
| 环境及时间源边界 | [正式环境CSV](tgoskits/research/cross-path-20261017/results/factorial-environment.csv)、[计数器报告](tgoskits/research/cross-path-20261017/results/counter-report.md) |
| 完整冷重放 | [已完成重放报告](tgoskits/research/cross-path-20261017/results/frozen-replay-complete-v1-report.md) |

[factorial_runner.py](tgoskits/research/cross-path-20261017/factorial_runner.py)负责一次性运行，[summarize-factorial.py](tgoskits/research/cross-path-20261017/summarize-factorial.py)按完整区组统计，[stage_baseline.py](tgoskits/research/cross-path-20261017/stage_baseline.py)关联阶段；重放应使用报告绑定的归档源码。0/A组仍运行Linux CPU对照负载，B关闭不表示Linux VM空闲；内存逻辑读写量不等于实测DRAM带宽。不要对当前源码直接执行旧finalize脚本并将其输出当作历史验证。

### 2.2 追加条件与当前候选

强度队列和有限相位候选分别保存输入与证据。连续B没有独立内存峰值时标，不能用连续负载冒充已受控相对相位。

| 内容 | 当前入口 |
| --- | --- |
| 强度敏感性预登记与运行状态 | [设计计划](tgoskits/research/cross-path-20261017/design/phase2-intensity-sensitivity-plan.md)、[96次固定计划](tgoskits/research/cross-path-20261017/configs/intensity-v3-plan.json)、[控制器状态](tgoskits/research/cross-path-20261017/results/intensity-v3-status.json) |
| 前缀审计与后续状态 | [前84次审计](tgoskits/research/cross-path-20261017/results/intensity-v3-progress-084-report.md)；后续检查点见进度页 |
| 强度冷重放工具与已有证明 | [重放计划](tgoskits/research/cross-path-20261017/design/intensity-source-replay-plan.md)、[首个完整大区组重放](tgoskits/research/cross-path-20261017/results/intensity-replay-macro1-v1-report.md) |
| 全96次审计与冷重放 | [真板完整审计](tgoskits/research/cross-path-20261017/results/intensity-v3-full-audit.json)、[全量冷重放独立审计](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v2-audit.json)；原控制器、第二轮原回放及独立审计实际退出均为0 |
| 完整强度交付与封存 | [Spec](tgoskits/research/cross-path-20261017/results/intensity-v3-complete-delivery-spec-review-v1.md)、[Quality](tgoskits/research/cross-path-20261017/results/intensity-v3-complete-delivery-quality-review-v1.md)、[最终交付](tgoskits/research/cross-path-20261017/results/intensity-v3-final-delivery.json)、[18,465文件新封存](tgoskits/research/cross-path-20261017/SHA256SUMS.intensity-v3-v1)、[现有只读验收](tgoskits/research/cross-path-20261017/results/intensity-v3-final-delivery-readiness.json) |
| 首轮复现历史与观测缺口 | [完整产物独立审计](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v1-output-audit.json)、[原wait未知](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v1-terminal-observation.json)；保留首轮事实，最终交付由第二轮实际wait=0支持 |
| 真板与统计规范初查 | [初查说明及真实执行](tgoskits/research/cross-path-20261017/raw/intensity-v3-spec-precheck-v1/precheck.md)；保留当时的原生数据、随机顺序、压力/环境及均值交互初查；正式双审见上方完整交付 |
| 有限相位与时间域 | [相位设计](tgoskits/research/cross-path-20261017/design/phase2-relative-phase-design.md)、[计数域报告](tgoskits/research/cross-path-20261017/results/counter-domain-isolated-v1-report.md) |
| C生产者及Host消费 | [C组件报告](tgoskits/research/cross-path-20261017/results/compact-linux-worker-v2-report.md)、[Host设计](tgoskits/research/cross-path-20261017/design/phase2-compact-host-integration-design.md) |
| 当前init接入候选 | [仅相位init设计](tgoskits/research/cross-path-20261017/design/phase2-phase-only-init-design.md)、[实施计划](tgoskits/research/cross-path-20261017/design/phase2-phase-only-init-plan.md) |
| QEMU失败后的验证路径 | [严格真板功能设计](tgoskits/research/cross-path-20261017/design/phase2-strict-native-verification-path-design.md)、[设计审阅](tgoskits/research/cross-path-20261017/results/phase2-strict-native-verification-path-design-review.json)、[实施计划](tgoskits/research/cross-path-20261017/design/phase2-strict-native-verification-path-plan.md)、[计划审阅](tgoskits/research/cross-path-20261017/results/phase2-strict-native-verification-path-plan-review.json)；原候选与修订要求保留，[v2离线验收](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-offline-acceptance-v2.md)已完成Spec→Quality和Root复制复验，主96次现已完整交付封存；AB1实际失败与后项未执行见下方当前记录 |
| 候选注释与Guest说明 | [带注释的prepare.py](tgoskits/research/cross-path-20261017/raw/compact-host-phase-init-v1/task1/source/virtualization/axvm/tests/guests/linux-load/prepare.py)、[Guest README](tgoskits/research/cross-path-20261017/raw/compact-host-phase-init-v1/task1/source/virtualization/axvm/tests/guests/linux-load/README.md)、[两文件补丁](tgoskits/research/cross-path-20261017/raw/compact-host-phase-init-v1/task1/evidence/source-change.patch) |
| 相位候选源码提交 | [23文件组合补丁](tgoskits/research/cross-path-20261017/patches/strict-native-phase-v1-candidate.patch)、[身份与使用范围](tgoskits/research/cross-path-20261017/patches/README-strict-native-phase-v1.md)；已提交`aafcffb3c`，独立副本重建702源通过，原正常功能仍失败 |
| 原严格真板AB1 | [实际单次启动](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-root-launch.json)、[宿主所有权见证](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-host-preflight-v1.json)、[失败审计报告](tgoskits/research/cross-path-20261017/results/strict-native-phase-v1-AB1-failure-audit-v1.md)、[最终失败交接](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-root-final-handoff-v1.json)、[失败证据双审状态](tgoskits/research/cross-path-20261017/results/strict-native-phase-v1-AB1-actual-review-state-v1.json)、[89文件封存](tgoskits/research/cross-path-20261017/SHA256SUMS.strict-native-phase-v1-AB1-failure-v1)；Trace dropped=19839，真实xtask/driver均退出1，释放unknown、工件链false，AB0/0未启动 |
| 捕获工具离线修订 | [设计](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-design.md)、[计划](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-plan.md)、[追加格式补充](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-append-format-addendum-v1.md)、[离线交付](tgoskits/research/cross-path-20261017/results/strict-native-fit-capture-repair-v1.md)；新副本完整事后使用链、Spec→Quality及Root接纳通过，已提交`742c23722`，不回填原失败，无新板卡任务 |
| 新测量容量候选 | [设计](tgoskits/research/cross-path-20261017/design/phase2-native-trace-capacity-v2-design.md)、[计划v2](tgoskits/research/cross-path-20261017/design/phase2-native-trace-capacity-v2-plan-v2.md)、[计划复审](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-design-plan-review-v2.md)；[Task1离线报告](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1.md)已交付，fmt、Clippy29/29及ready通过，[独立Spec](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-spec-review-v1.md)已PASS，[Quality](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-quality-review-v1.md)及[Root副本验收](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-root-acceptance-v1.md)也已通过；新版AB1在构建准备阶段失败，[失败与缓存目录原因](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-AB1-prepare-failure-v1.md)已保存，无新Guest/Trace；后两项停止 |
| 缓存目录修订v3 | [Task1交付](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-task1.md)、双审及[Root副本验收](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-task1-root-acceptance-v1.md)通过；AB1实际导出42,768条Trace，dropped/incomplete均0，两策略DATA、相位及压力门通过；[最终交接](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json)记录外层920秒超时、xtask实际wait未知、driver及原工具会话均退出1、release未知，AB0/0停止；[完整正常审计](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json)仍拒绝，[失败报告](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-failure-v1.md)、[退出调查](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-exit-cause-structured-v1.md)及[审计原因](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-auditor-cause-structured-v1.md)已保存，控制器最终wait和Host容器解析修订待验证 |
| 正常功能审计器 | [使用范围与版本](tgoskits/research/cross-path-20261017/patches/README-native-function-auditor-v3.md)、[运行身份修订](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v3-revision-v1.json)、[合并质量审查](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v3-quality-review-v1.md)；逻辑及新环境准确绑定通过双审，尚无新真板正常GREEN |
| 相位分析的前置门槛 | [分析设计](tgoskits/research/cross-path-20261017/design/phase2-phase-analysis-design.md)、[v2协议补充](tgoskits/research/cross-path-20261017/design/phase2-phase-analysis-v2-protocol-addendum.md) |

[强度控制器](tgoskits/research/cross-path-20261017/intensity_sensitivity.py)成功终结后自动调用[固定汇总器](tgoskits/research/cross-path-20261017/summarize-intensity.py)，随后才用[冷重放入口](tgoskits/research/cross-path-20261017/intensity_replay.py)完成全量重放、审阅与新封存。相位功能通过后仍须对应版本的开销和真板随机重复；设计、离线检查或构建成功不等于这些项目完成。

## 3. 诊断、源码注释与历史证据

失败也是实验记录，但其证据范围必须单独标明。工具失败、预期负例契约通过和正常运行通过分别判断，不能因某个检查器退出0而扩大整个系统的通过范围。

### 3.1 当前诊断链

按以下顺序查看相位回传缺口；各报告保留当时实际退出、工件和未知项。

| 记录 | 证据范围 |
| --- | --- |
| [原Host失败](tgoskits/research/cross-path-20261017/results/compact-host-runtime-v2-failure-report.md) | 原诊断回传不完整 |
| [GDB v2实际报告](tgoskits/research/cross-path-20261017/results/compact-host-GDB-v2-actual-once-report.md) | 有界观察及工具清理缺口 |
| [离线清理修订](tgoskits/research/cross-path-20261017/results/GDB-cleanup-zombie-fix-v1-report.md) | 清理规则红绿证明，不回填旧目标失败 |
| [GDB v3实际报告](tgoskits/research/cross-path-20261017/results/compact-host-GDB-v3-actual-once-report.md) | 稀疏观察仍未取得完整诊断 |
| [PID1单次对照](tgoskits/research/cross-path-20261017/results/compact-host-PID1-control-v1-report.md) | 原严格诊断负例契约通过，额外13B收尾仍不完整 |
| [实际证据双审状态](tgoskits/research/cross-path-20261017/results/phase2-PID1-control-actual-review-state-v1.json) | 精确SHA、批准范围和未通过项 |
| [首个正常AB相位失败](tgoskits/research/cross-path-20261017/results/compact-host-phase-init-v1-actual-report.md) | 生产时间界拒绝，另有Trace丢样、SGI容量和收尾错误；后续序列停止 |
| [本次失败双审状态](tgoskits/research/cross-path-20261017/results/phase2-phase-init-actual-review-state-v1.json) | Spec与Quality仅批准如实失败交付，正常功能仍未通过 |
| [测量与回传生命周期核查](tgoskits/research/cross-path-20261017/results/phase2-phase-init-failure-lifecycle-v1.md) | 同域时间、CPU3容量和资源调用顺序；不作全部丢样或迟到的唯一归因 |

源码注释重点解释时间域与单位、有限/连续生命周期、结果提交与失败保留、资源关闭所有权。本次生命周期、fresh见证、清理所有权及未知wait的注释已随候选源码和补丁归档；运行中及已封存版本的解释由配套文档承载，避免注释变更破坏实验身份。英文代码注释说明原因和不变量，中文文档说明实验用法和边界。

### 3.2 封存与历史阅读

[研究目录旧README](tgoskits/research/cross-path-20261017/README.md)已进入原封存，内容按历史检查点追加，开头状态较旧。它用于追溯过程；当前状态以根目录进度页和明确的后续验收为准。

原封存清单为[SHA256SUMS](tgoskits/research/cross-path-20261017/SHA256SUMS)，后续冷重放和验收清单为[SHA256SUMS.postseal-v1](tgoskits/research/cross-path-20261017/SHA256SUMS.postseal-v1)。整理文档保留这些路径和原字节，后续结果另行追加、核验和封存。PMU/Cache事件归属、带宽控制权限及活跃窗口恒频仍须各自证据，不能由设备节点或版本文本推定。
