# function-audit-v2 独立 Spec 复审

结论：**PASS（限定为原三个逻辑阻断的闭合）**，`blockers=[]`。可对当前准确候选进入 Quality；这不是正常功能、硬件或未来 freeze 的批准。

绑定 `status.json` SHA `51a710820c85f11900a5b156a764a314c6464e15ed147cb2dfb0747cf87f9af6`、`audit.py` SHA `1e4f19515aa9bc285e1201a85378a166f7b7a7805067ab4b4f6032fa1ad0a22b`；修订报告 SHA `2e0b813adb79d2ec6718382fd61720ad1909124c80de189ae737beb4f868ba73`。完整证据与精确位置见同名 JSON。

| 原阻断 | v2 闭合证据 |
| --- | --- |
| SPEC-FAILURE-AND-TAIL-GATE | `audit.py:123–164,524–537` 分类并拒绝已知失败、非零错误、未分类error候选；suite实际消费候选。非空无LF最终字节独立记录，包含不匹配marker的 `LINUX_PHA`。原始span/首错/错误字节保留。 |
| SPEC-RAW-WORKLOAD-PROTOCOL | `audit.py:221–315,370–384` 索引并逐策略绑定LOAD/MEMORY readiness与全部progress；policy入口调用真实workload判定，检查顺序、CPU已知答案、进展单调及DATA前后累计内存。Boff的所有progress实际访问值须零，原DATA/fence门保留。 |
| SPEC-TRACE-AND-PHYSICAL-IDENTITY | `audit.py:453–504` 从准确冻结源提取EventKind闭集，真实逐事件循环校验完整字段/顺序/u64；HostIrqEntry固定CPU0/thread0/INTID30/current_el，ARM固定INTID30/CPU0。原zero-loss/实际导出数/连续sequence门保留。 |

完整普通diff和函数AST对照确认：wire/DATA、压力、生命周期、工件、源/工具/环境、退出/释放判定函数均未变，policy与Trace只增加上述门。仍精确绑定 `0f46…` 源和 `6d83…` 旧freeze，未接纳未来版本占位。v1 audit/status原字节保持。

已核现有真实收据及stdout/stderr身份，没有重跑测试：同一最终规则测试在v1真实wait1，18项漏检失败/0 error；v2真实wait0，18个相同反例均拒绝；继承2项检查wait0。Trace仅使用准确SHA旧696日志的两个真实Marker/HostIrqEntry行，先过相同wire字段baseline，再局部变异并执行真实逐事件循环；没有FROZEN、suite或成功Trace合成。这些只证明工具规则RED/GREEN。

两份整体真实失败输入仍wait1。旧AB1的dropped19839、release unknown不变；当前最终handoff `30d261…` 仍无DATA/Trace/工件，九项正常门拒绝，xtask/driver/Root实际wait为1/1/1、无强停、owned group empty、release unknown。AB0/0未执行，原quota不重试。

正常端到端GREEN、实际Aoff/Bzero、成功完整Trace/suite/工件链/释放、legacy RED/GREEN和完整Host继续独立列为未验证。未来缓存v3及新freeze不在本复审范围；容量问题、Host、M2、Joint和goal均未因此完成。Host pulse/ack仍仅保留为非阻断测量字段建议。
