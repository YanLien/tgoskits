# 阶段四证据协议草案

该协议用于真板执行，不把 QEMU 输出当作性能结论。所有组均复用已校准的 Guest ISR 时间戳和 Host/Guest 时钟关系；1 ms 轮询确认只记录为独立观察窗口。

## 固定实验组

| 组 | 配置 | 目的 |
|---|---|---|
| Baseline | 原始 AxVisor，`IRQ_SERVICE=off` | 原始尾延迟和普通 VM 成本 |
| IRQ-only | 仅中断服务路径改动 | 分离 IRQ 处理收益 |
| Scheduler-only | 仅 vCPU 就绪/运行策略改动 | 分离调度收益 |
| Joint | IRQ + vCPU 协同 | 检验耦合是否带来额外收益 |
| Ablation | 去掉 Deadline/slack 反馈或 bounded 限制 | 检验策略必要性 |

每组固定 Guest 镜像、vCPU 数、物理 CPU 亲和性、频率策略、温度区间、IRQ 路由、样本数和实验时长。每个干扰场景至少保留原始日志、二进制身份、配置快照和 SHA-256。

## 场景矩阵

1. 无干扰：单实时 Guest 周期任务。
2. CPU 竞争：普通 Linux Guest 计算负载。
3. 内存竞争：固定工作集的读写压力，并记录 PMU/带宽计数。
4. 中断负载：可复现的定时器或设备事件速率梯度。
5. I/O/DMA：仅在 E 方向能力核查通过后执行。

## 每条样本的最低字段

`source, host_irq_entry, irq_dispatch_done, service_kick, ready_enqueue, running_start, guest_entry, guest_isr_start, guest_isr_end, host_guest_calibration_id, calibration_error_ns, ack_observed_ns, trace_loss, deadline_ns, deadline_miss`。

报告 P50/P95/P99/P99.9/max、样本数、校准误差、Deadline miss ratio、普通 VM 吞吐、监控开销和异常样本。`ack_observed_ns` 不得进入 ISR 延迟分布。

## 判断规则

只有当阶段一数据显示 IRQ 服务、vCPU 等待和共享资源干扰存在稳定的可量化耦合，才保留 Joint 作为论文机制。若 Joint 不优于单项机制，或收益只是转移到普通 VM，不扩大实现范围；记录观测、假设和保证边界。

## 当前 QEMU 字段映射与未实现字段

当前 QEMU 日志中的 `VIRQ_ISR_SAMPLE.guest_ticks` 是 Guest C ISR 内第一处计数读取，可作为 `guest_isr_start`；`observed_ticks` 是 Host 侧确认窗口的结束观察点，经过校准后只能得到独立的 `c_isr_to_host_observation` 区间。当前夹具没有 Guest ISR 结束时间，因此不能报告 ISR 执行时长；也没有统一的 `deadline_miss` 字段，`deadline_to_entry_ns` 只描述物理 PPI 的入口相对比较器 deadline 的观测间隔。

当前 runtime/Ready 事件可覆盖 `host_irq_entry`、`service_kick`、`ready_enqueue`、`running_start` 和 `guest_entry` 的关联；校准误差由 before/after counter offset 区间表示。阶段四真板采集仍必须补充 Guest ISR 结束标记、明确 deadline 判定规则和 trace-loss 状态，不能把当前 QEMU 的 `observed_ticks` 或缺失字段填充为替代值。
