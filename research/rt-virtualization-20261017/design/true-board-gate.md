# 真板执行门禁

该门禁把 `论文提要.md` 的真板要求转成可审查步骤。当前文件只提供模板和判定规则；没有 RK3588 运行记录时，不得把模板中的 `null` 填成推测值，也不得把 QEMU 日志复制为真板数据。

## 进入实验前

1. 固定板卡型号、SoC revision、ATF/U-Boot、Linux、DTB 和 Guest 镜像哈希，填写 `configs/true-board-run-template.json`。
2. 读取并归档 CPU cluster、频率/温度策略、PMU counter 数量/宽度/PMCEID/IRQ。
3. 确认 DSU/cache 分区权限；若未通过，跳过方向 D。
4. 确认 SMMU 版本、实例、stream ID、stage-2/直通模式和 IOTLB 事件；若未通过，跳过方向 E。
5. 对每个计数器做空载、CPU 竞争、内存竞争和 DMA 竞争变化性检查，并估计监控开销。

## 首轮只允许的实验

- `Baseline/off`，单实时 Guest，无干扰；重复轮次和样本数先固定。
- 同配置 `inherit`，仅用于验证 A0 的事件链和安全回滚。
- 匹配的 CPU 竞争组，确认 vCPU Ready/Running 分解在真板上可见。

只有这三组的 Guest ISR 校准、trace loss、Deadline miss 和计数器归属都通过，才可以进入 memory/interrupt 干扰矩阵。只有阶段一显示 IRQ 服务与 vCPU/共享资源尾部存在稳定耦合，才允许设计 Joint；否则保留单项机制和负结果。

## 禁止的推断

- Host acknowledgement 或 1 ms 轮询时间不能进入 Guest ISR 时延。
- QEMU 的 P99、bounded 31 ms 尾部或服务等级 witness 不能替代真板性能。
- 最大观测值不能写成 WCET/WCRT；没有形式化证明时只报告观测边界。
- PMU 计数可读不等于计数归属于某个 VM；必须记录 vCPU 运行区间和切换结算规则。
