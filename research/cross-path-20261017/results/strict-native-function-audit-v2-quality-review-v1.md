# 严格真板外部功能审计器 v2 独立质量审阅

本报告记录完整实现的独立质量判断、准确证据身份及仍待闭合的退出收据绑定问题；结论不覆盖任何新的硬件运行或正常功能成功。

## 1. 审阅结论

本次结论为 **FAIL**，有一个证据绑定阻断 `QUALITY-EXIT-RUN-IDENTITY`。本次首次完整独立通读 [audit.py](../raw/strict-native-phase-v2/function-audit-v2/audit.py) 全部 813 行，覆盖继承实现、三处 Spec 修订、错误传播与保存工件链。三处修订的局部规则证据仍成立，但当前候选尚不能据此接纳为完整正常功能审计器。

### 1.1 准确候选

本审阅仅适用于已核字节的候选与准确 Root final handoff。当前 source702 与工具 freeze 保持原身份，未来 v3 cache 候选尚无新 freeze，不在本结论内。

| 材料 | SHA256 |
| --- | --- |
| `audit.py`，57,661 B | `1e4f19515aa9bc285e1201a85378a166f7b7a7805067ab4b4f6032fa1ad0a22b` |
| `status.json`，11,060 B | `51a710820c85f11900a5b156a764a314c6464e15ed147cb2dfb0747cf87f9af6` |
| 修订报告 | `2e0b813adb79d2ec6718382fd61720ad1909124c80de189ae737beb4f868ba73` |
| 新 Spec 复审 PASS | `c771cd092714f6cd505601cbd9846f36856a882f8b4fddc91829e48bc15b93e7` |
| 新 AB1 Root final handoff | `30d2613204648b7ebd89a202ee642b725678c94c056dada23e58de34b88cdd91` |
| source702 | `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb` |
| 工具 freeze | `6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9` |

完整路径、其余引用与实际检查结果保存在[本次 JSON](strict-native-function-audit-v2-quality-review-v1.json)。依据为[容量计划 Task2](../design/phase2-native-trace-capacity-v2-plan-v2.md)及[继承计划 3.1/3.2](../design/phase2-strict-native-verification-path-plan.md)。项目 `test-quality` 与 `orthome-verification` 规则用于区分工具拒绝证明、静态实现和真实后端功能。

### 1.2 结论边界

本次没有运行既有测试、审计器、build、ready、QEMU、板卡、proc、signal、网络或 Git，也没有全扫 cache、702、9642 或主96。仅新增这份报告及 JSON，原 v1、修订候选、历史报告与失败材料均保持原字节。

本次不批准硬件、不恢复已耗尽 quota，也不批准 Host、容量修复、M2、Joint 或 goal。即使后续该绑定阻断闭合，完整正常端到端 GREEN、AB0/0、Aoff/Bzero、成功 Trace/suite/工件链/release 与 legacy 生命周期仍须各自取得真实证据。

## 2. 退出证据阻断

`validate_exit()` 必须证明当前 case 的实际 xtask、driver、Root 都正常退出并通过固定 ostool 显式释放。当前实现严格检查数值与释放状态，但没有完成收据到当前启动的身份连接。

### 2.1 已存在但未消费的身份

[audit.py:721](../raw/strict-native-phase-v2/function-audit-v2/audit.py#L721) 只读取退出值、`Popen.wait` 文案、清理/释放字段及 `root_wait.run_result_sha256`。该哈希只绑定两份收据彼此相符；函数不读取它们的 `case_id`，也不核 `root_wait.driver.argv`、PID/starttime 或 `launch_sha256`。实际外层退出还可取 `handoff.actual_root_wait_exit` 标量。

[audit():755](../raw/strict-native-phase-v2/function-audit-v2/audit.py#L755) 仅加载六份文档，没有加载 handoff 已提供的 `root_launch` 和 `root_tool_completion`。`validate_source()` 将 `actual_command` 与固定 cwd/argv/environment 绑定，却没有把 wait 所属的原始 child 连到它。

这些字段无需新造：当前真实 [Root wait](../raw/strict-native-phase-v2/AB1-root-wait.json) 已有 `case_id`、`driver.argv/pid/pgid/starttime`、`driver_pid_from_Popen`、`launch_sha256` 和 `supervisor_source_sha256`；[Root launch](../raw/strict-native-phase-v2/AB1-root-launch.json) 及[原始工具完成收据](../raw/strict-native-phase-v2/AB1-root-supervisor-completion-v1.json) 也都在准确 final handoff 中。这三份文件的 SHA/size 已独立核实。

### 2.2 影响与最小修订

静态反例是：保持当前 case 的正常日志、工件和 `actual_command`，把另一 case 的真实成功 `run_result/root_wait` 作为一对引用。只要这对收据内部哈希匹配、零退出、无强停且声明显式释放，现有退出门不会消费其中不同的 `case_id` 或 `driver.argv --run`；源/环境门也不检查这组 wait。因此它不能独立证明这些退出与释放属于本次启动。

这属于静态证据绑定错误，不是“正路径尚未验证”的同义表述。本次仅做源码及 AST 字段访问分析，没有执行这个反例、没有运行 `validate_exit()`，也没有构造成功 Guest 或 Trace。当前准确新 AB1 的身份字段本来相符且实际退出均为 1；没有证据表明它发生了错配。

修订应复用已有 launch/wait/completion，连接当前 case、准确 driver 启动 argv、source/freeze/批准输入、原始 Popen child 身份与 Root 实际完成结果；错配或缺失保持非零。对这个通用绑定行为补一个窄拒绝证明即可，无需成功日志替身、逐字段常量清单或硬件重试。新候选冻结后重新先 Spec 后 Quality。

## 3. 完整实现与现有证据

除上述阻断外，本次对整个审计链未发现其他需要阻断的静态问题。以下结论仍以准确冻结实现为范围，正向运行兼容性并未由静态审阅证明。

### 3.1 正常门与错误路径

`load_wire()` 只提取准确源码的四个纯函数与常量，并拒绝通过 `-O` 禁用 assert。`validate_fixture()/validate_policy()/validate_workload()` 保留 64 个 T6、每策略 32 槽/2 快照、两份实际 DATA/R/ACCEPT、已知答案、generation/cookie/counter、前后校时、精确 250µs/4ms 和 Boff 全部原始工作量零访问。原始 Guest 顺序用于 workload 阶段，延后的 Host 打印没有被当成 Guest 执行顺序。

`validate_pressure()` 继续检查固定 SGI grid/checksum/因果、全部 B/T6 覆盖及 skip0，Aoff 要求明确无事件。`runtime_event()/validate_trace()` 从冻结 `EventKind` 提取闭集，核完整字段、u64、PPI30/CPU0/current_el、逐 CPU 连续 sequence、实际导出数、64 次物理 IRQ 和单一全局零丢样。

`Log` 保存首错、全部 DIAG/候选、DATA 与原始跨度；`validate_suite()` 消费所有失败分类并拒绝非空无 LF 尾字节。两组退休、RT 完成、前后校时和最终 suite 保留。各 gate 聚合失败，不允许后续成功覆盖原始错误。`validate_artifacts()` 逐项核 17 份保存工件，沿原始生产日志、FIT default/hash、Host initramfs、嵌入 Guest/RT/DTB/rootfs/resources 与实际 worker 构建链绑定，并明确标记 post-exit。

### 3.2 实际做过的检查

本次新执行的三个 `python3 -B` 内联只读检查均退出 0：SHA/size 与 AST；退出身份字段访问及准确六份现有材料；最终 RED/GREEN JSON 与真实原始跨度比较。没有执行被解析的代码。鲜核范围包括 status 的 13 项文件、source contract 的 17 项准确引用、5 份真实收据及其 stdout/stderr、4 个 Python 文件的 AST 语法，以及 v1/v2 的 19 个未变、5 个修改、3 个新增顶层函数。没有删除函数。

现有测试按 `test-quality` 判定保留：两个继承检查保护真实 DATA wire/CRC 和旧失败；三个规则组保护工作量、失败/残尾、事件 schema/路由的不同后果。独立核实同一最终 18 个局部反例的原始跨度与突变完全相同：v1 实际 wait1、18 失败且 0 errors；v2 实际 wait0、18 全部拒绝且 0 errors。继承两项实际 wait0，两份真实整体失败审计仍实际 wait1。

Trace 规则仅使用准确 SHA 为 `b7d63e456db20e93756a94f665734afbfb588a69610d24cfa85231bbcc2002f8` 的旧 intensity log 中两条真实 Marker/HostIrqEntry，不能当成完整成功 Trace 或新 Guest 结果。

### 3.3 真实失败与未验证项

新 v2 AB1 在 host prepare 的 Git 入口失败，没有 Guest/DATA/Trace/工件链；xtask、driver、Root 实际均为 1。没有强停，owned group 已空，release 仍 unknown，AB0/0 保持未执行。原 v1 dropped19839、旧 source/freeze 和事后补充工件链均不回填为成功。

完整正常端到端 GREEN、三项完整真板功能、正常显式释放、legacy RED/GREEN 和完整 Host 都未验证。后续必须先闭合本次收据绑定阻断，不能用本次质量审阅或既有局部规则 GREEN 批准硬件或扩大研究结论。
