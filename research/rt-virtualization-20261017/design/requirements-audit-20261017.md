# 论文提要要求—当前证据审计

审计日期：2026-10-17（Asia/Shanghai）。依据仓库根目录 `论文提要.md`、`AGENTS.md` 和当前分支实际文件；本记录区分“已验证”“证据不足”和“外部阻塞”。

## 阶段一：低侵入测量

| 要求 | 当前证据 | 判定 |
|---|---|---|
| Host IRQ 到 Guest ISR 的可校准链 | `raw/current-qemu-ppi-{baseline,inherit,bounded}-600.log`；对应 `results/replay/current-qemu-ppi-*/physical/`；每策略 600/600，保留 `VIRQ_CLOCK_SAMPLE` 与 Guest `VIRQ_ISR_SAMPLE` | 已在 QEMU 验证 |
| vCPU Ready/Running 分解 | 各 replay 目录的 `runtime/`、`ready/` 和 `comparison.json`；runtime/Ready 均 600/600 关联 | 已在 QEMU 验证 |
| 不把 1 ms 轮询当 ISR 延迟 | `results/conclusion.md`、分析器 limitations；`ack_observed_ns` 未进入 ISR 指标 | 已验证口径 |
| 共享资源干扰识别 | `linux-matched` 只覆盖 QEMU CPU 负载生命周期；`hardware-capability-audit.md` 明确无 RK3588 PMU/DSU/SMMU 证据 | QEMU 夹具完成；真板干扰未验证 |

阶段一尚不能声称“实际硬件瓶颈已确定”。当前只能提出 QEMU 假设：`submit→IRQ`、`worker→Running` 和 `Running→GuestEntry` 可能贡献尾部；该假设须在真板匹配实验中复核。

## 阶段二：独立、可回滚机制

- A0 位于 `axvm::diagnostics::irq_service`，三态 `off`/`inherit`/`bounded`，生产构建关闭，测试路径保留清理和回滚语义。
- `raw/witness-v2-*.log`、`patches/freeze-verification.json` 和 `patches/limit-sensitivity.json` 证明了调度顺序、限流和资源释放的功能路径。
- 当前分支 600 样本 QEMU 运行证明三态可以重建；`bounded/FIFO` 约 31 ms 尾部是限流代价记录，不是收益。

判定：原型正确性和可回滚性已在 QEMU 验证；没有性能收益、硬实时保证或普通 VM 公平性结论。

## 阶段三：耦合后才协同

论文提要要求先证实瓶颈耦合，再实现 Deadline 感知联合策略。当前没有真板 CPU/内存/设备干扰计数，也没有 `IRQ-only`、`Scheduler-only`、`Joint`、去反馈消融的匹配结果。因此阶段三**未启动**，不把 A0 的服务等级继承称为最终协同机制。

## 阶段四：可复现证据包

已具备：原始软件基线、已有 PL031/Linux 负载基线、当前分支 PPI 三模式、配置快照、分析脚本、provenance、校验清单和结论边界。未具备：

1. RK3588 真板 `off` 匹配基线及重复轮次；
2. PMU/Cache/DSU/DRAM 带宽计数与监控开销；
3. 方向 A/B 的可比已有方法基线；
4. 真板 IRQ-only、Scheduler/Budget-only、Joint 和消融矩阵；
5. Deadline miss、普通 VM 吞吐和跨干扰类型统计区间。

## 外部阻塞与下一可执行门

当前主机为 x86_64 Intel，不能生成 RK3588 的真实性能证据；方向 D/E 的目标硬件能力也未通过核查。该阻塞不影响 QEMU 分析、协议和归档维护，但阻止阶段三/四的硬件结论。下一可执行门是取得固定版本的 RK3588 板卡、固件、DTB、PMU 权限和可重复 Guest 启动环境，然后按 `design/phase4-evidence-protocol.md` 先跑 `off`/匹配基线，再决定是否扩展 A0 或转向 B。

## 字段完整性复核

当前 QEMU 链已实现 Guest ISR 起点和 Host/Guest 校准，但没有 Guest ISR 结束时间，也没有统一的 `deadline_miss` 字段；因此阶段四协议中的 ISR 执行时长、Deadline miss ratio 和完整真板样本契约仍未完成。`observed_ticks` 只属于 Host 确认窗口，继续排除在 ISR 时延之外。该缺口不影响当前“到 Guest ISR 起点”的 QEMU 测量结论，但阻止阶段四完整证据包宣称完成。
