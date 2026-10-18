# function-audit-v2 修订交付

三个 Spec 阻断已在新的 [`function-audit-v2/`](../raw/strict-native-phase-v2/function-audit-v2/README.md) 修订候选内处理，等待独立 Spec 复审；尚未进入 Quality。原 v1 不改。

失败/非零错误/残尾均明确拒绝；完整原始 workload readiness/progress 加入逐策略、已知答案和阶段内存累计核验，Boff 全部进展必须零访问；每条 Trace 强制准确 EventKind/完整字段，HostIrqEntry 必须 PPI30/CPU0/current_el，ARM 路由也逐项核对。`pulse_ns/ack_observed_ns` 继续只保留测量原件，没有新增硬件时间阈值。

同一三个窄规则测试组在 v1 产生 18 个预期漏检失败（实际 wait1），在 v2 的 18 个局部突变均拒绝（实际 wait0）。Trace 仅使用 Root 指定旧696日志内两条真实事件，直接运行审计器原逐事件循环；没有添加 FROZEN/summary/suite 或构造成功 Trace。继承的两项真实 DATA/CRC 与失败保留检查实际 wait0。精确输入、原始跨度、突变前后记录和全部命令的 Popen.wait 收据见 [`status.json`](../raw/strict-native-phase-v2/function-audit-v2/status.json)。

两份真实整体失败仍实际审计退出1：旧 AB1 dropped19839/releaseunknown 保留，新 v2 仍在 host_prepare 失败且没有 Guest/DATA/Trace/工件，xtask/driver/Root 都为1、releaseunknown。完整正常端到端 GREEN、AB0/0、Aoff/Bzero 真成功、成功 Trace/suite/工件链/释放及 legacy 生命周期仍未验证。

当前 source702 与 freeze 精确绑定未变，未来路径/freeze 未确定且未填占位。未修改冻结源/工具/cache、Root材料、历史报告或v1；未执行 board/QEMU/build/ready/proc/signal/network/Git，未扫描主96/702/cache，没有性能、重叠或 I_AB 产物，Host/M2/Joint/goal 均未完成。
