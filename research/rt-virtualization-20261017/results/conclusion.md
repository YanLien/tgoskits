# 本轮结果与保证边界

归档日志由 `analyze_virq_irq_service.py` 复核：

- `witness-v2-off.log`：Fair/FIFO 均在 blocker 结束后进入 Guest ISR。
- `witness-v2-inherit.log`：仅 FIFO 目标在 blocker 仍运行时进入 Guest ISR。
- `witness-v2-bounded.log`：FIFO witness 同样在 blocker 内完成；本组主要验证服务策略和派发上限路径。
- `throttle-bounded.log`：128 条样本、7 次实际等待；`--require-throttle` 的 Guest 时间跨度下界检查通过。

这些结果只证明测试构造中的调度顺序、配置身份和清理协议。它们没有证明自然负载上的 P99.9 改善、普通 VM 公平性、硬件共享资源隔离或硬实时上界。FIFO witness 组使用人为 50 ms blocker，不能与普通性能分布合并。

## 校准 PPI 复放观察

`replay_archived_ppi.sh` 对 `ppi-off/inherit/bounded.log` 各自重新执行物理 IRQ、Guest ISR 校准和尾部审计。每个策略包含 Fair/FIFO 各 128 条样本，Host/Guest 计数频率为 62.5 MHz，校准区间宽度约 1.0--1.1 µs。当前-EL PPI 组的 `entry_to_kick` P99 约为 19--38 µs，而 `entry_to_c_isr` P99 上界约为 0.48--0.97 ms；这支持继续检查 vCPU 就绪/运行链路是否是 QEMU 观测中的主要变量。

`c_isr_to_host_observation` 仍约为 1 ms 量级，它是 Host 观察窗口的剩余部分，不是 Guest ISR 时延，未进入上述 ISR 指标。三种模式来自不同 QEMU 启动，样本量和运行环境不足以形成统计性能比较；该表只用于复现测量链和决定真板实验的分解字段。

本轮没有进行外部推送、PR、合并、部署或发布。
