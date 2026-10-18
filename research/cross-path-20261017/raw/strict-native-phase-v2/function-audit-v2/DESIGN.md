# function-audit-v2 三项 Spec 修订

本次仅修复 [v1 Spec FAIL](../../../results/strict-native-function-audit-v1-spec-review-v1.md) 中三个阻断，审阅 JSON SHA `98737fba25ea1a1ac3fb0c2fcf1f61359e7f9625e4e9e2d23366349ae4b48560`。v1 保持原字节；不重做硬件、构建、cleanup 或主队列验证。

| 阻断 | 冻结合同及修订 |
| --- | --- |
| SPEC-FAILURE-AND-TAIL-GATE | `irq_pressure.rs:244–255` 的 failure 与 `support/mod.rs:365–380` 的已知失败均拒绝；所有非零 errors/dropped/incomplete 明确分类并拒绝。一般 error 候选标为 `unclassified-reject`，suite 必须消费分类，不再静默。任何非空无 LF 最终字节均保留 span 并拒绝，包括 `LINUX_PHA`；允许完整有 LF 的普通工具尾文及明确的空白尾字节，没有猜测成功文本白名单。 |
| SPEC-RAW-WORKLOAD-PROTOCOL | 按 `linux.rs:431–529`、`linux_phase.rs:757–772`，收集并逐策略绑定 LOAD_READY/MEMORY_READY/全部 PROGRESS；核 readiness 顺序、批次严格递增且为256倍数、CPU0与 CPU checksum。DATA 前内存累计必须0，DATA后为256×B；每条logical_bytes/memory_checksum独立已知答案。Boff的所有原始进展都必须零访问。Guest transcript 的原顺序用于阶段判断，Host 的延后打印位置不充当Guest阶段。 |
| SPEC-TRACE-AND-PHYSICAL-IDENTITY | 从准确 SHA 的 `diagnostics.rs:33–89` 提取合法 EventKind 闭集；逐事件要求完整且精确字段/顺序/u64。HostIrqEntry 必须CPU0、thread0、INTID30、value1=1(current_el)，对应 `diagnostics.rs:289–307`。逐条 ARM 的INTID30/CPU0对应 `vcpu_runtime.rs:1280–1285`。原全局zero-loss/导出数/逐CPU连续sequence门保留。 |

`pulse_ns/ack_observed_ns` 保留为原始测量字段，未添加性能阈值，不把它们声明为独立功能证据。702 仍为 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，当前工具 freeze 仍精确绑定 `6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`。未来版本的路径/freeze 尚未确定，本次不填占位或放宽绑定。

三个完整解析行为使用三个规则测试组保护，18个局部反例分别代表 readiness、工作量/累计阶段、schema/路由、失败及残尾的独特后果。全部取自封存旧失败 AB1 的真实记录，或 Root 指定 `intensity-v3-b01-irq2x-0-32.log` 中的两条真实事件。后者SHA为 `b7d63e456db20e93756a94f665734afbfb588a69610d24cfa85231bbcc2002f8`，来自旧696，仅证明同wire字段规则，不能作为新相位成功证据。

同一 `test_review_rules.py` 在v1产生18个预期漏检失败（真实wait1），在v2三个规则组均通过（真实wait0）。failure测试直接执行真实suite拒绝前缀，event测试直接执行真实逐事件循环；AST只用于截取被测实现本身，不新增摘要/冻结行、成功Guest或整套成功Trace，也不复制recorder/时序算法模型。原始完整输入、局部跨度、突变前后字节、被测代码SHA及结果保存在规则JSON中。

这些是外部审计器规则 RED/GREEN。两份真实整体失败输入仍真实审计退出1，旧 dropped19839/释放unknown不回填，新v2仍无Guest/DATA/Trace/工件。完整正常端到端GREEN、AB0/0、Aoff/Bzero真实成功、完整Trace/suite/工件链/正常释放、legacy RED/GREEN及整个Host均未验证，M2/Joint/goal均false。新Spec通过后才进入Quality。
