# D/E 硬件能力核查

核查日期：2026-10-17（UTC）。原始主机快照见 `raw/capability-host.txt`。

## 观察结果

当前实验主机是 x86_64 Intel Core i7-11800H，运行 Linux 7.1.9。它暴露的是 Intel CPU/uncore PMU 事件源；不是 RK3588 AArch64 板卡，因此不能用本机结果证明 RK3588 的 DSU、SMMU/IOMMU、ARM PMUv3 或 AxVisor 真板行为。

本机有 21 个 Linux IOMMU group，但这只证明当前 x86 主机内核建立了 IOMMU 分组，不能证明目标板的 SMMU 拓扑、IOTLB 计数器、直通路径或 DMA 竞争行为。没有发现可用于 RK3588 DSU 配置或 SMMU 计数器的目标板设备树/寄存器运行时证据。

仓库源码具备 `arm-smmu-v3`、RK3588 PCI、RK3588 cpufreq 和 AArch64 PMU 相关构建入口；这些是工程支持线索，不是硬件能力证明。现有 Orange Pi 5 Plus 配置也明确把 PMU 访问、DTB、固件和板卡部署作为独立前置条件。

## 结论和门禁

- 方向 D：**未通过能力核查**。需在目标 RK3588 上确认 DSU/缓存分区接口、固件权限、频率/温度状态和可观测 PMU 事件；在此之前不实现 Cache/DSU 动态策略。
- 方向 E：**未通过能力核查**。需确认 SMMU 版本和拓扑、IOMMU/IOTLB 事件计数、设备直通配置、失效路径及 DMA 设备；在此之前不实现 IOMMU/DMA 治理策略。
- 方向 A 继续作为当前主线。方向 B 的 PMU 监管只有在真实板卡能力和计数归属协议确认后再启动。

## 上板前最小核查清单

1. 固定板卡型号、SoC revision、启动固件/ATF/U-Boot、内核和 DTB 哈希。
2. 记录 CPU cluster、DSU 拓扑、频率/温度控制权限，以及每 CPU PMU counter 数量、宽度、PMCEID 和 IRQ。
3. 记录 SMMU 实例、stream ID、stage-2/直通模式、IOTLB 失效方式和可读事件计数器。
4. 用单 VM 空载、CPU 竞争、内存竞争、DMA 竞争四组最小实验验证计数器会变化且不会把监控中断混入 Guest ISR 时延。
5. 只有上述证据齐全后，才把 D/E 纳入阶段四比较矩阵。
