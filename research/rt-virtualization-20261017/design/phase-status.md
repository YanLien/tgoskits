# 四阶段执行状态

## 阶段一：测量

已完成 QEMU 测量链和离线分析器。每个样本分别保留 Host IRQ 入口、服务 kick、Ready 入队、Running、Guest entry 和 Guest C ISR 计数；前后校准区间必须相交。`ack_observed_ns` 仍只是确认观察窗口，不能代替 ISR 时间戳。

已覆盖的软件 edge、CNTP PPI、PL031 SPI、低 EL/Guest-running、同核 CPU、跨核私有内存工作集和独立 CPU Linux VM。真板采集、PMU 计数和 DRAM/Cache 干扰尚未完成。

已有的一次软件中断 QEMU 基线包含 600 条 Host 样本（Fair/FIFO 各 300）和对应 Guest ISR 校准记录，已纳入归档复放；其 `ack_observed_ns` 仅作 Host 观察窗口，不进入 ISR 时延。另有一组 600 条 PL031 SPI + Linux Guest CPU 干扰样本已纳入复放，用于验证负载生命周期和跨 VM 事件分解，但仍不等价于真板 DRAM/Cache 干扰。

当前分支又完成了一次真实 QEMU 运行，物理 PPI 基线 Fair/FIFO 各 600 条，runtime/Ready 均 600/600 完整关联；该结果与历史日志分开保存，作为当前代码和当前构建配置的功能/测量链证据。

## 瓶颈判断

现有 witness 不是自然负载性能结论，而是对已观测路径的因果构造：低等级 CPU0 FIFO blocker 覆盖第一条物理 PPI 的 deadline。`off` 下 FIFO Guest ISR 在 blocker 结束后出现；`inherit` 和 `bounded` 下 FIFO ISR 在 blocker 结束前出现，Fair 目标不继承。这个结果足以支持阶段二先验证服务调度路径，但不足以证明 Deadline 机制收益。

## 阶段二：最小原型

`axvm::diagnostics::irq_service` 只在 AArch64 `axtest` 路径编译。`off` 是原始基线；`inherit` 让 FIFO 目标的 deferred worker 使用目标策略；`bounded` 在 worker 自有状态上增加每窗口派发轮数上限。配置范围为 1–256 轮、100–100000 微秒，默认 8 轮/1 毫秒。生产构建不启用该模块。

原型不改变 IRQ pending、IPI、Guest 注入、VM stop/join 和资源释放所有权。它不是 CPU 预算、IRQ 速率上限、滑动窗口保证或 Deadline-aware 策略。

## 阶段三和四：未完成项

- 还没有证明自然 CPU/内存/设备负载下的尾延迟收益。
- 还没有与 IRQ-only、Scheduler-only、Joint 及去掉反馈的消融组完成匹配实验。
- 还没有 RK3588 真板、PMU、Cache/DSU、IOMMU 或 DMA 证据。
- 方向 B 的 VM 级内存带宽预算尚未实现；方向 C 只有独立 CPU 的 Linux 负载夹具。
- D/E 已完成本机预核查，但当前主机是 x86_64 Intel，不能证明 RK3588 的 DSU/SMMU 能力；真板核查清单已归档，未提前实现硬件依赖策略。

下一步应先在真板复现 `off/inherit` 的匹配基线，报告 P95/P99/P99.9、Deadline miss、普通 VM 吞吐和服务开销，再决定是否把 A0 扩展为真正的 Deadline Slack 协同机制。
