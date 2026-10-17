# 本轮结果与保证边界

归档日志由 `analyze_virq_irq_service.py` 复核：

- `witness-v2-off.log`：Fair/FIFO 均在 blocker 结束后进入 Guest ISR。
- `witness-v2-inherit.log`：仅 FIFO 目标在 blocker 仍运行时进入 Guest ISR。
- `witness-v2-bounded.log`：FIFO witness 同样在 blocker 内完成；本组主要验证服务策略和派发上限路径。
- `throttle-bounded.log`：128 条样本、7 次实际等待；`--require-throttle` 的 Guest 时间跨度下界检查通过。

这些结果只证明测试构造中的调度顺序、配置身份和清理协议。它们没有证明自然负载上的 P99.9 改善、普通 VM 公平性、硬件共享资源隔离或硬实时上界。FIFO witness 组使用人为 50 ms blocker，不能与普通性能分布合并。

本轮没有进行外部推送、PR、合并、部署或发布。
