# function-audit-v3 修订交付

`QUALITY-EXIT-RUN-IDENTITY` 已在新的 [`function-audit-v3/`](../raw/strict-native-phase-v2/function-audit-v3/README.md) 修订候选中处理，等待独立Spec→Quality。旧v1/v2及历史报告保持原字节。

新增同次运行身份门，连接case、批准/实际命令、准确driver启动参数、launch/wait原child与supervisor身份、原Popen PID、收据SHA和Root原session completion。完整退出/释放门另核全0与显式释放，不能由身份通过替代；外层退出不再退回只读handoff标量。

同一窄测试在原v2产生8个预期漏拒（真实wait1），修订后8个错配均拒绝（真实wait0）。测试基线是实际失败AB1收据，保留非零退出与releaseunknown，没有造成功Popen/Guest/Trace。原18规则和2继承检查仍实际wait0，两份真实完整失败仍审计wait1。当前新AB1同次运行身份门通过，正常功能仍false；旧v1缺completion明确拒绝，不回填。

当前0f46源码/6d830c工具绑定不变。Root后续已通知新缓存准确freeze `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`；待本版封口和审阅后，另起副本仅迁移准确合同/路径，不在本版改绑。全部准确SHA、收据、变化字段与测试字节见 [`status.json`](../raw/strict-native-phase-v2/function-audit-v3/status.json)。未执行硬件/QEMU/build/ready/proc/signal/network/Git，未修改缓存、Rust、Root材料或历史，也未全扫主96/702/cache。

完整正常端到端GREEN、AB0/0、正常Trace/suite/工件链/释放和legacy生命周期未验证；不放行下一阶段，Host/M2/Joint/goal均未完成。
