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

进一步的运行链分解显示，128/128 条样本都完成了 `IRQ -> worker -> Running -> GuestEntry` 关联。以 `off/fair` 为例，P99 的 `irq_to_worker`、`worker_to_running`、`running_to_entry` 和 GuestEntry 后 ISR 区间分别约为 234、189、591 和 53 µs；Ready 子段的 `wake_to_ready` 与 `ready_to_running` P99 分别约为 18 和 174 µs。它说明 QEMU 当前样本的尾部主要分布在服务唤醒、vCPU 运行前等待和偶发运行到 GuestEntry 的路径，而不是 1 ms 观察窗口本身。

这只是测量链中的瓶颈假设：不同启动的策略数值不能当作 A0 的性能比较，也不能据此跳过真板匹配基线。阶段三仍须在真板确认同一分解和共享资源干扰是否耦合后再实现 Deadline Slack 协同。

## 600 条宿主侧样本复用

归档的 `software-baseline-600.log` 复放成功，包含 Fair/FIFO 各 300 条 Host 样本及对应校准 Guest ISR 记录。复放脚本输出同时保留 Host `pulse_ns`、`ack_observed_ns` 和 Guest ISR 区间；报告只把校准后的 ISR 区间用于 ISR 尾延迟，明确排除 1 ms 轮询确认时间。该基线用于样本量和协议复核，不代表真板性能，也不与 128 条物理 PPI 组混合比较。

## Linux Guest CPU 干扰复放

`linux-interference-600.log` 同样包含 Fair/FIFO 各 300 条，来源为 PL031 SPI，Linux Guest 在 Host CPU3 运行固定批量 CPU 负载，服务放置和每条样本的 Ready 关联均通过分析器校验。该组可用于验证“共享 vCPU/Guest 负载下的事件链和负载进度”字段；它不能证明 DRAM/Cache 竞争，因为日志只提供 Linux 批次进度和逻辑负载计数，没有真实板 PMU/带宽计数。

该组的 Guest ISR P99 上界约为 Fair 727 µs、FIFO 748 µs；Host 观察窗口 P99 上界约为 947 µs、1.024 ms。两者严格分列，不能用后者替代 ISR 时延。当前证据足以保留 A 方向并准备真板匹配实验，尚不足以启动 D/E 或把 QEMU 负载差异写成性能收益。

此外，`linux-matched-baseline-600.log` 提供了相同 PL031 SPI 配置下的无 Linux 负载对照，`replay_linux_matched.sh` 对两组统一执行同一分析器。该对照只解决 QEMU 配置/来源不一致问题；它仍然不是硬件共享资源基线，且 Linux Guest 的批次进度不是 DRAM 带宽计数。任何负载组差异都只能作为上板实验的假设和参数选择依据。

## 当前分支复跑

当前分支使用离线 pinned Zephyr、CMake/Ninja 和 AArch64 toolchain wrapper 完成了新的 600-sample `physical_timer_ppi` QEMU 基线。Fair/FIFO 各 600 条，校准区间宽度约 1.07/1.12 µs，`entry_to_c_isr` P99 上界约 598/659 µs，runtime 与 Ready 链均 600/600 完整。该运行证明当前代码、配置和测量链可以重建，但它仍然是 QEMU 功能证据；不能与真板性能、共享微架构资源或硬实时上界混同。

同一分支随后完成了 `inherit` 和 `bounded`（8 轮/50 ms）各 600 条样本。两种模式均通过 `AXTEST_SUITE_OK`，runtime/Ready 链均 600/600 完整。`inherit` 的 `entry_to_c_isr` P99 上界为 Fair/FIFO 约 1.034/0.623 ms；`bounded` 为约 0.592/31.120 ms，其中 bounded/FIFO 的 31 ms 尾部是限流原型在该 QEMU 构造下的可观测代价，不能解释为硬件收益或保证。三组仍需真板匹配实验，当前仅证明原型模式可回滚、测量链可复现。

本轮没有进行外部推送、PR、合并、部署或发布。
