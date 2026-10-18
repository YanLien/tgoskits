# function-audit-v1 独立 Spec 审阅

结论：**FAIL**。完整正常门的实现候选尚有三项已确证缺口，当前不进入 Quality。正常正路径缺少 GREEN 作为独立未完成证据列出，不用它替代静态审阅。

审阅绑定 `status.json` SHA `3f2e487e8c87d816a204b3132fd0a097d07aaa9f88dc029611892d3061ff9a32`、`audit.py` SHA `14f93a9a22ead29ad5b8b6b0d112078ba6fae407746d705c553a29fedeccfaf3`；当前最终 handoff SHA `30d2613204648b7ebd89a202ee642b725678c94c056dada23e58de34b88cdd91`。完整输入及证据身份见同名 JSON。

| 阻断 | 精确位置（audit.py） | 影响及所需修复 |
| --- | --- | --- |
| SPEC-FAILURE-AND-TAIL-GATE | 21–23、123–141、403–415 | `VIRQ_IRQ_PRESSURE_FAILURE`、一般 `errors=1` 可只成为不影响suite的候选；截断到 `LINUX_PHA` 的无LF残尾不被观察。补齐已知失败与非零错误拒绝、候选分类及协议残尾检查，保留首错/span。 |
| SPEC-RAW-WORKLOAD-PROTOCOL | 21、197–221、246–251、284–321 | 没有独立审计 `LINUX_LOAD_READY/PROGRESS`，`LINUX_MEMORY_READY` 未被marker覆盖。冻结 `linux.rs:431–529`、`linux_phase.rs:757–772` 的readiness/单调进展/CPU已知答案/阶段内存累计合同没有落实，Bzero可漏矛盾观察。 |
| SPEC-TRACE-AND-PHYSICAL-IDENTITY | 274–283、356–383 | Trace的kind缺失或闭集外值不拒绝；64个HostIrqEntry只按名称计数，未核INTID/context；ARM路由字段亦忽略。补合法事件schema与固定PPI30/current-EL路由，保留全局零loss及逐事件数/连续sequence。 |

已存在的门包括两份原始DATA/R解码、32槽/2快照、64T6已知答案、同代counter映射、64次前后校时交集、250µs/4ms、A覆盖/skip0及off分支、退休顺序、零loss/实际导出数量、post-exit FIT/initramfs/rootfs链和三层真实wait/释放判据。它们不抵消上表的缺口。

新的窄检查只在旧真实失败观察上改坏单条workload checksum或ARM INTID，policy门仍接受；没有构造正常成功日志，没有运行整体audit或目标。`pulse_ns`负向突变亦被接受，但其独立功能后果尚未证成，本次只列建议。检查首轮残尾样例选择错误产生真实wait1，源码/收据保留；换成协议前缀后的窄检查真实wait0。证据位于 `raw/strict-native-function-audit-v1-spec-review-v1/`。既有两项工具检查及两次实际失败审计没有重跑。

当前v2 AB1仍在host_prepare失败：原始log 2283B、DATA/Trace/工件为零，xtask/driver/Root实际wait均1，无强停，owned group empty，release unknown；九项正常门拒绝。空Git refs目录缺失的既有根因报告只作准确SHA引用，本审阅未重扫或修cache。AB0/0未执行，原quota不重试。旧AB1 dropped19839及其失败均保留。

正常完整端到端GREEN、AB0/0、Aoff/Bzero真实路径、完整成功Trace/suite、工件链和成功显式释放都未验证；legacy RED/GREEN及完整Host仍欠缺。容量问题、Host、M2、Joint与goal均未完成。

由原实施者在新版本修复三个阻断并冻结新身份，重新Spec通过后才进行Quality。既有候选、源/工具/cache、Root wrapper和历史报告未改；本次仅新增审阅材料。
