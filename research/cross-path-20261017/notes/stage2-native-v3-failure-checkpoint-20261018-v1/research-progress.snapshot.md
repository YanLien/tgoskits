# AxVisor跨路径干扰研究进度

更新于 2026-10-18T13:25:03.893936+00:00。

本文只记录当前结果、队列和下一步。设计、报告、复现工具及历史诊断按[研究文档索引](README.md)查找；研究依据[《论文提要》V3.0](论文提要.md)。所有正式材料保存在本目录树，阶段0～2尚未整体完成；已按用户“继续吧”恢复工作。

## 1. 当前结果

原软件测量协议的M1通过。新增96次强度数据出现满足预登记经验规则的正、负交互候选，已完成全量冷重放、Spec→Quality审阅和新封存；机制未验证，M2未通过，当前不推进联合优化。

### 1.1 里程碑

[阶段0～1验收](tgoskits/research/cross-path-20261017/results/phase01-final-acceptance.md)判定原软件测量协议的M1通过，M2未通过。T4为软件Entry，T6为任务线程完成；校时、残余探针及阶段重叠均有边界，最大观测值不称严格WCET/WCRT。

原正式条件下，两个策略、两个端点的四个均值交互经验95%区间均跨零，尚无稳定交互证据。这一结果仅适用于已测条件，不能推广为所有负载均无耦合。

### 1.2 已有真板交付

RK3588上的双VM、中断压力A、内存压力B及软件T0～T6关联已跑通。原四组完成8个随机平衡区组、32次启动、2048个任务；2028条严格阶段链，20个歧义任务保留端点，Trace dropped/incomplete为0，DMR时钟区间[0,0]。

[四组正式报告](tgoskits/research/cross-path-20261017/results/factorial-report.md)包含均值交互、尾延迟、DMR及Linux吞吐；[阶段关联报告](tgoskits/research/cross-path-20261017/results/factorial-final-stage-association-report.md)说明分解分母。[记录操作开销](tgoskits/research/cross-path-20261017/results/recorder-ops-report.md)来自8对启动、1024个任务，量化范围包含时间戳、IRQ守卫、登记、预留及写入，不称全部探针成本；off丢样状态保持未知。

## 2. 正在推进的实验

强度队列和相位测量使用分别冻结的版本。QEMU仅验证功能，真实Cache/内存干扰结论继续依赖真板。

### 2.1 强度敏感性

96次真板启动、6144个任务已全部接受并完成本批次交付。[最终交付记录](tgoskits/research/cross-path-20261017/results/intensity-v3-final-delivery.json)绑定原计划、状态、完整审计、全量冷重放、两份正式审阅及[新封存](tgoskits/research/cross-path-20261017/SHA256SUMS.intensity-v3-v1)。新清单覆盖18,465份文件，逐项重新读取SHA通过；旧两份封存、旧研究README及论文提要保持原字节。现有入口的[实际只读验收](tgoskits/research/cross-path-20261017/results/intensity-v3-final-delivery-readiness.json)也已退出0，核原生数据与静态输入均匹配；严格真板AB1冻结入口已于08:59:56 UTC单次启动，见[实际启动与父进程wait约定](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-root-launch.json)。固定输入重核通过，AB1一次性标记已建立，实际板卡已运行；已因Trace丢样失败，xtask及driver真实wait均为1，AB0/0未启动，详见2.2节。

[原控制器退出记录](tgoskits/research/cross-path-20261017/results/intensity-v3-controller-exit.json)确认会话52334实际退出0并自动生成汇总，[宿主退出核验](tgoskits/research/cross-path-20261017/raw/intensity-v3-controller-exit-host-v1.json)绑定同一宿主启动及准确原进程身份。[全96次审计](tgoskits/research/cross-path-20261017/results/intensity-v3-full-audit.json)核696源码/52控制/2基础输入、3552派生文件、192运行均值和2016环境行。6144个端点全部保留，6118条严格阶段链；26个关联歧义任务仅排除阶段子集，Trace丢样记录为0。

[强度报告](tgoskits/research/cross-path-20261017/results/intensity-v3-report.md)交付12个层/策略/端点组合的均值交互及经验95%包围、尾延迟、DMR和Linux吞吐。4个负、1个正满足预登记候选规则；正项为memory_sparse/Fair的IRQ入口到任务完成，均值时钟界8.872～14.562µs，经验95%包围8.133～15.370µs。候选要求至少7/8块同号，前后半及逐块留一均值界同号。八块小样本的逐点经验包围不保证覆盖率或全族覆盖，候选尚未证明传播机制或优化收益。各条件观察DMR界为[0,0]；每格256样本的P99.9等于观察最大值，不称严格WCET/WCRT；Linux逻辑读写吞吐不等于DRAM带宽。

[全量冷重放独立审计](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v2-audit.json)实际退出0，原回放子进程也由准确父进程`Popen.wait()`记录退出0，并经同一真实宿主退出核验。全部96份raw与3552派生重新消费冻结源码，3456文件字节一致，96个decoder仅允许raw路径重定位；1731份实际进程导入记录核到恢复目录及准确SHA。最终3份CSV、报告和4份PNG字节一致，JSON仅有实际状态/decoder/PDF的101处身份绑定变化；4份PDF仅创建时间不同，独立72dpi重渲染一致。第一轮复现曾丢失外层句柄，其[完整产物核验](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v1-output-audit.json)和[真实wait未知记录](tgoskits/research/cross-path-20261017/results/intensity-v3-cold-replay-v1-terminal-observation.json)保持原状；本次交付使用第二轮实际退出证据，两轮均未启动硬件任务。

[正式Spec](tgoskits/research/cross-path-20261017/results/intensity-v3-complete-delivery-spec-review-v1.md)随后[Quality](tgoskits/research/cross-path-20261017/results/intensity-v3-complete-delivery-quality-review-v1.md)均在`complete_intensity_v3_delivery`范围Approved，无未解决问题；Root分别鲜核82项与100项证据绑定。研究整体仍未完成：新版matched trace on/off及受控相位敏感性尚未交付，M2、Joint均未通过。原正式32次报告与本轮强度结果分别按各自冻结版本和条件解释，不回写旧结论。[前84次审计](tgoskits/research/cross-path-20261017/results/intensity-v3-progress-084-report.md)及各准备、前缀与失败记录保留历史身份。

### 2.2 有限相位测量

当前新缓存v3的AB1已结束，正常功能仍未通过。[完整正式审计](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json)确认实际导出42,768条Trace、dropped=0、incomplete=0，两策略各32个任务、完整DATA、相位时间界、压力及两组回收门通过，原始日志保留suite pass。整轮却触发920秒外层超时，清理报`owned group leader argv changed`；xtask实际wait未知，driver和原控制器会话77494均实际退出1，release未知。[最终交接](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json)保留该失败和未知项，AB0/0停止；不生成本次相位性能或正常GREEN。[审计原因调查](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-auditor-cause-structured-v1.md)已定位拼接Host包被单archive解析器拒绝、两条DTS Warning被error词命中；实际USER_CACHE与离线见证路径也不同，选择原因尚未验证。[退出调查](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-exit-cause-structured-v1.md)已用本地真实子进程复现合法exec触发argv拒绝，确认最后一次poll之后漏收最终wait；历史AB1实际exec身份仍未知。[本次失败报告](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-failure-v1.md)单独保留原24门20过4拒，原审计不回写。13:05 UTC的[宿主及服务观察](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/AB1-host-terminal-observation-v1.json)显示原进程组已空、板卡可用1，仅证明当前状态，不补写原退出码或释放成功。

以下原v1/v2失败保持各自身份，AB0、0与legacy仍未执行。原v1严格真板AB1已实际执行并失败，两个策略各保留32条T6、完整DATA及正常相位ACCEPT，但随后`VIRQ_TRACE_FROZEN`报告records=22343、dropped=19839、incomplete=0，全局零丢样门失败；正常逐事件Trace导出为0，不能把保留计数当作已导出的事件。[失败审计报告](tgoskits/research/cross-path-20261017/results/strict-native-phase-v1-AB1-failure-audit-v1.md)保留首错、原始字节、实际Trace范围及未验证项，不生成正常相位性能结果。[失败证据双审状态](tgoskits/research/cross-path-20261017/results/strict-native-phase-v1-AB1-actual-review-state-v1.json)已完成Spec→Quality，仅批准如实失败交付；[新封存](tgoskits/research/cross-path-20261017/SHA256SUMS.strict-native-phase-v1-AB1-failure-v1)覆盖89份文件、118,559,853B，逐项重读通过，正常功能仍false。

[真实父进程wait](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-root-wait.json)确认driver退出1，xtask也退出1；没有强制signal，owned group已空，[真实宿主终态](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-host-terminal-v1.json)核原三份进程身份已消失、后两组无marker和输出。释放保持unknown。[捕获报告](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1/capture.json)另报`FIT component has no integrity hash`，工件链false；17份保存工件仅完成文件身份核对，不以事后重建补齐。[最终交接](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/AB1-root-final-handoff-v1.json)与[32文件索引](tgoskits/research/cross-path-20261017/results/strict-native-phase-v1-AB1-root-evidence-index-v1.json)均已保存，源码、生产时间界及预算未放宽。

已对保存FIT作[离线结构读取](tgoskits/research/cross-path-20261017/raw/strict-native-followup-v1/FIT-structure-readonly-v1.json)：default配置选中的kernel、ramdisk和fdt均无内置hash子节点，原捕获工具要求该字段而拒绝。原工具与工件保持不变。[捕获修订设计](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-design.md)、[实施计划](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-plan.md)及[格式补充](tgoskits/research/cross-path-20261017/design/phase2-native-fit-capture-repair-append-format-addendum-v1.md)均已审阅。新副本允许缺内置hash并明确记录缺席，仍校验存在的hash；追加包仅复用同权限空目录，拒绝重复普通文件和类型/权限冲突。[离线交付](tgoskits/research/cross-path-20261017/results/strict-native-fit-capture-repair-v1.md)的完整真实AB1补充捕获实际wait=0、工件使用链true、errors为空，原FDT转换、Host嵌入、rootfs、init AST、worker编译及case尾门均通过。Root恢复后重新读取206份索引文件及报告、核对最小函数差异通过；[Spec](tgoskits/research/cross-path-20261017/results/strict-native-fit-capture-repair-spec-review-v1.md)随后[Quality](tgoskits/research/cross-path-20261017/results/strict-native-fit-capture-repair-quality-review-v1.md)均PASS且无阻断，Root另鲜核85份当前引用并完成[接纳](tgoskits/research/cross-path-20261017/results/strict-native-fit-capture-repair-root-acceptance-v1.json)，已提交为`742c23722`。该结论仅为事后补充使用链，不回填原Trace丢样、原工件链失败、正常功能或释放状态。

[板卡服务只读快照](tgoskits/research/cross-path-20261017/raw/strict-native-followup-v1/board-service-readonly-status-v1.json)显示目标类型有1块可用、旧AB1会话查询404，只证明该时刻状态，不补写原运行释放成功。本轮未新占板。离线命令曾在启动前报ENOSPC，随后[宿主和默认沙箱复查](tgoskits/research/cross-path-20261017/raw/strict-native-followup-v1/disk-startup-recovery-v1.json)已成功、约6GB可用；未删除历史材料，原因未确定。

当前推进[追踪容量修订](tgoskits/research/cross-path-20261017/design/phase2-native-trace-capacity-v2-design.md)。新普通源仅将每CPU `CAPACITY` 从16,384改为65,536，另701份源及追踪热路径、原子序、压力输入、时间界均保持父版本。[计划v2](tgoskits/research/cross-path-20261017/design/phase2-native-trace-capacity-v2-plan-v2.md)已解决新cache入口仍指向旧venv的问题，并通过[独立复审](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-design-plan-review-v2.md)。容量变化增加测量内存，不能称为优化收益，仍须新版本匹配开销。

[Task1离线报告](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1.md)已交付：fmt实际退出0，项目Clippy29/29通过；真实新cache的Python/CMake入口通过；同一冻结候选ready实际0、错误source及approval各拒绝2，没有marker或板卡任务。归档155项约104MB、69项冻结工具及702份源均已核验。[独立Spec](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-spec-review-v1.md)已PASS、无阻断，170项检查实际wait0；[独立Quality](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-quality-review-v1.md)也已PASS、无阻断，Root另核116项当前引用通过；[Root独立副本验收](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-task1-root-acceptance-v1.md)已完成，副本ready实际0、正式执行因冻结根限制拒绝2、准确父进程wait0，target元数据未变。启动wrapper的收据异常wait路径已修复；同一实际Popen块的两个本地故障注入均取得RED1→GREEN0，[独立复审](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-AB1-wrapper-review-v1.md)已PASS。新版AB1单次控制器于11:23:06 UTC[实际启动](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v2/AB1-root-launch.json)，11:24:15 UTC结束，失败在`host_prepare`的Zephyr Git检查；xtask、driver及原统一exec会话15037实际退出均1，没有强制signal、owned group已空，release保持unknown。没有新Guest数据或Trace，AB0/0停止；[失败与原因报告](tgoskits/research/cross-path-20261017/results/strict-native-trace-capacity-v2-AB1-prepare-failure-v1.md)已保存，v2单次marker保留，不重试该候选。Root已在独立临时元数据副本证明：文件清单复制漏了空`.git/refs`目录，仅补该目录后Git解析固定版本并核干净工作树均退出0，25份Git文件字节未改；原冻结cache仍拒绝128。该局部证明只解释构建入口失败，不能证明容量修复。下一候选须保留并核验所需目录结构，先证明真实Git及生产准备入口。[完整正常功能审计候选](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v2/function-audit-v1/status.json)已交付，新旧失败审计均明确拒绝，真实wire及CRC损坏等两项工具检查通过；[独立Spec](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v1-spec-review-v1.md)确认失败/残尾、原始workload协议、Trace与物理IRQ身份三处逻辑缺口，[新v2修订](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v2-revision-v1.json)已交付，同一18条规则反例完成原实现RED1→修订GREEN0，两份真实失败仍拒绝；[Spec复审](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v2-spec-review-v1.md)已PASS；[Quality审阅](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v2-quality-review-v1.md)发现唯一阻断：退出收据未连接当前case、原driver child、Root启动和原工具完成。当前实际AB1并未发现错配，其1/1/1失败保持。[独立v3修订](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v3-revision-v1.json)已交付：同次运行独立门保留真实失败身份可验证，8条收据错配完成RED1→GREEN0，18规则和2继承检查通过，两次真实失败仍拒绝；[Spec复审](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v3-spec-review-v1.md)及[合并Quality](tgoskits/research/cross-path-20261017/results/strict-native-function-audit-v3-quality-review-v1.md)已PASS；[精确新缓存合同](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-function-audit-metadata-migration-v1.md)也已核定，35函数未改。正常端到端GREEN仍未得。

已按用户“继续推进阶段2”启动[缓存目录修订v3计划](tgoskits/research/cross-path-20261017/design/phase2-native-cache-topology-v3-plan.md)的独立审阅：Rust和9642份普通文件保持容量v2字节；用保留目录的复制、目录权限manifest和真实生产host_prepare解决构建缺口，验证后另冻结新身份。[计划审阅](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-design-plan-review-v1.md)已PASS，Task1在新普通副本离线实施，真实固定Git入口已通过，完整生产准备实际wait=0、用时72.17秒，已生成Zephyr及Linux资源，worker身份不变；该离线准备未启动板卡，随后正式AB1见本节开头。准备后出现45个能力缓存及原log追加，第一次冻结正确拒绝。Root逐项核定为固定Zephyr按新编译器绝对路径生成的结果，已写[准确生成缓存补充](tgoskits/research/cross-path-20261017/design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md)；[定向审阅](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-generated-cache-addendum-review-v1.md)已PASS；目录缺失真实拒绝2、恢复后最终ready0，freeze为0bf9ff1c，107项工具已冻结，[Task1报告](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-task1.md)及归档已交付，独立Spec→Quality均PASS；[Root副本验收](tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-task1-root-acceptance-v1.md)实际ready0、正式拒绝2、父Popen和原会话81327退出0，原target7784项metadata不变且无marker；生成cache没有runtime例外。初始helper把任意路径组件cache误作缓存，命中合法fs源码后停止；已定位为离线过滤断言问题，保留首错并在未冻结副本修正根目录判断，不消耗目标额度。原v2额度和失败不改。

离线准备的异常及真实退出均保留在[Task1证据目录](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v2/task1/)：固定kernel/base原路径缺失后，Root从同SHA/大小/权限的既有归档[恢复输入](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v2/base-input-restoration-v1.json)，首次ready拒绝记录及未知丢失原因不改；慢归档helper因循环内反复解析24MB清单而停滞，Root通过pidfd仅停止准确自持离线进程，原统一exec实际退出143，修正版新输出目录真实Popen.wait=0。候选冻结身份未变，没有信号父进程、进程组、旧进程或硬件；审阅器对系统GCC链接的首次比较错误及修正后的检查也分别留存。

以下保留本次真板路径之前的候选与失败来由；相位分析、同版本开销和真板相位随机重复仍未完成。原13B诊断负例、严格QEMU失败与本次真板失败分别按实际版本和证据范围解释。

[单次生命周期对照](tgoskits/research/cross-path-20261017/results/compact-host-PID1-control-v1-report.md)收到完整1023B诊断，原严格负例检查器退出0；实际仍有13B `LINUX_LOAD_FA`收尾残缺，未见完整失败行、worker返回或init退出标记，根因未知。实际证据已完成Spec→Quality，[审阅状态](tgoskits/research/cross-path-20261017/results/phase2-PID1-control-actual-review-state-v1.json)只接受窄负例契约和有限证据，未判整个Host或正常相位通过。

[仅相位init设计](tgoskits/research/cross-path-20261017/design/phase2-phase-only-init-design.md)及[计划](tgoskits/research/cross-path-20261017/design/phase2-phase-only-init-plan.md)已审阅，候选通过Spec→Quality及Root独立复制目录复验，实际退出0；正常702仅prepare.py与README变化。生命周期、fresh见证、清理所有权和QEMU未知wait的注释已补齐，源码和补丁均归档。

随后唯一strict AB/phase1运行实际退出1，正常相位未通过：完整9810B诊断保留两边界、32槽，首错phase_timing；还出现SGI容量耗尽、Trace dropped10424及16B收尾残缺，无正常DATA/ACCEPT。后续AB0、0/phase0与legacy序列已停止，未重跑或放宽界限。[本次失败报告](tgoskits/research/cross-path-20261017/results/compact-host-phase-init-v1-actual-report.md)及[155文件归档审计](tgoskits/research/cross-path-20261017/results/compact-host-phase-init-v1-actual-audit.json)已保存，[实际证据双审](tgoskits/research/cross-path-20261017/results/phase2-phase-init-actual-review-state-v1.json)只批准如实失败交付；Root再次逐项核验全部155文件，这不表示正常功能通过。

[生命周期核查](tgoskits/research/cross-path-20261017/results/phase2-phase-init-failure-lifecycle-v1.md)已核同域时间、CPU3满缓冲及诊断先于压力清理的调用关系，未证明迟到、全部丢样或残尾的唯一根因。[严格真板验证路径](tgoskits/research/cross-path-20261017/design/phase2-strict-native-verification-path-design.md)已通过独立设计审阅，[实施计划](tgoskits/research/cross-path-20261017/design/phase2-strict-native-verification-path-plan.md)及其[独立审阅](tgoskits/research/cross-path-20261017/results/phase2-strict-native-verification-path-plan-review.json)均已完成；板卡配置固定在隔离workspace内。[原离线候选](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/task1/task1-report.md)已冻结，Root逐项核对归档103文件。[原Spec审阅](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-spec-review.json)要求修订三项：leader退出后的进程组清理、最终合包路径和新增缓存成员检查。

[离线修订v2](tgoskits/research/cross-path-20261017/raw/strict-native-phase-v1/task1-revision-v2/revision-report.md)已冻结346文件，原候选和失败证据保留。[新Spec复审](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-spec-review-v2.json)在离线Task1范围内Approved，三项均解决、无新增问题；Root重新核对8项依据、42项冻结输入及实际工具身份。冻结报告中两个过时元数据字段由[独立更正记录](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-v2-report-clarification.json)说明，原报告字节不变。[Quality复审](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-quality-review-v2.json)也在同一离线范围内Approved，无未解决问题。[Root独立工具副本复验](tgoskits/research/cross-path-20261017/results/phase2-strict-native-task1-offline-acceptance-v2.md)已实际完成：会话75301退出0，主门及清理、最终包、缓存三个组件检查器均实际退出0，当时真实主门入口按前置拒绝2，当前主96完整交付后的入口通过见2.1节；110文件归档逐项核验完成，原103/346文件归档及工具冻结身份不变。Task1离线准备完成。清理局部证明只涉及自持Python进程，包路径证明在后续kernel身份门停止，完整捕获仍false；均不代表真实板卡功能或释放通过。



## 3. 阶段2的判定与待办

阶段2依据提要7.3节，用四组重复对照判断是否存在超出均值简单相加的稳定交互。没有稳定交互也应完整交付并报告否定或不确定结果。

### 3.1 四组实验

在同一环境中随机或交错运行E0/E1/E2/E3，改变强度与相对相位检查条件敏感性。

| 组别 | 中断压力A | 内存压力B |
| --- | --- | --- |
| E0（0） | 关 | 关 |
| E1（A） | 开 | 关 |
| E2（B） | 关 | 开 |
| E3（AB） | 开 | 开 |

按同一指标计算 `I_AB = mean(L_AB) - mean(L_A) - mean(L_B) + mean(L_0)`，报告重复运行的不确定性；P99/P99.9、截止期违约率、最大观测延迟和Linux吞吐分列，分位数非加性不能证明耦合。只有交互稳定才进入阶段3机制归因，机制证据成立后才实现联合优化。

### 3.2 下一步与验收缺口

下一项按固定顺序完成，任何未执行或失败项都保持未通过，不以设计、离线fake或构建成功替代目标证据。

| 工作 | 下一步及完成条件 |
| --- | --- |
| 强度队列 | 96次全部接受，原会话实际退出0及宿主机身份退出已核验；自动汇总完成 |
| 强度可复现交付 | 完整审计通过；全96次、实际wait=0、完整冷重放与双审均完成；新封存18,465文件及现有只读验收通过，本批次已交付 |
| 相位功能 | v3 AB1完整导出42,768条Trace且零丢样，DATA/相位/压力门通过；整轮外层920秒超时、清理argv身份拒绝、xtask退出及release未知，driver和原工具会话实际1，正常审计仍失败。失败证据和两项原因调查已保存；先修已批准Host拼包合同的审计实现，再修控制器收尾和核定缓存环境；AB0/0停止，legacy未执行 |
| 相位性能与测量开销 | 满足最终Host及分析门槛；先完成真实相位功能，再做同版本匹配开销和随机重复相位实验 |
| 文档与注释 | 总索引、当前进度及历史快照已整理；当前候选注释、Guest说明和补丁已归档，后续随真实状态更新 |

## 4. 证据与历史记录

已按用户提交代码的要求在 `tgoskits` 当前分支 `research/rt-cap-audit-20261017` 完成本地提交：`6d2443c9b` 保存92份测量代码及配置，`052f74240` 保存130份实验/统计/重放工具与冻结输入，`742c23722` 保存25份已双审的离线捕获修订及文档，`2f98ad751` 保存四项重放软件合同测试（实际wait0），`236275aee` 保存容量设计与现行计划、两轮审阅，`aafcffb3c` 以组合补丁保存原相位候选的23份修改/新增源，并核独立重建702份源SHA全匹配；`e15eaa663` 保存新版容量补丁、冻结工具/输入和离线双审及Root验收，共28文件；`1558c98da` 保存启动wrapper与收据异常wait的真实局部红绿证明，共13文件。另以`97f5bdecd`保存新v3计划/独立审阅及原v2构建失败和空目录原因证据，共21文件；新增`28febaab7`保存v3缓存目录门、实际生产准备和Root验收、正常审计器运行身份修订及准确新合同、注释补丁和审阅，共231文件；Root已核全部提交blob与准确SHA一致。已按用户指令推送到[远端研究分支](https://github.com/YanLien/tgoskits/tree/research/rt-cap-audit-20261017)，`git ls-remote`确认远端HEAD为`28febaab7b73c5c717b4306a1017880e50f26f16`；尚未合并。提交不改变既有实验身份与结论，原始Trace、构建缓存及尚未通过的相位候选保留原归档。准确清单和提交核对见[提交记录](tgoskits/research/cross-path-20261017/notes/code-commit-20261018-v1/)。

所有资料均在 `/home/yanlien/Program/hypervisor` 内，详细文件不通过移动或改写已封存材料来更新状态。

### 4.1 正式材料

原始Trace、环境快照、脚本、源码/工件、CSV及图表按[总索引](README.md)定位。新结果追加到 `tgoskits/research/cross-path-20261017/`，原失败和封存保留原字节；缺少固件二进制认证、活跃窗口恒频或硬件带宽控制等条件时明确记录，不从版本文本或设备节点推定能力。

### 4.2 历史过程

整理前的详细诊断经过已保存为[进度历史快照](tgoskits/research/cross-path-20261017/notes/research-progress-before-documentation-20261018.md)。[研究目录旧README](tgoskits/research/cross-path-20261017/README.md)属于已封存历史记录，其早期M1=false等描述不随当前验收回填；当前里程碑以1.1节及正式验收为准。
