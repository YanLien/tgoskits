# AxVisor 实时虚拟化研究归档

本目录记录 2026-10-17 基于 `research/rt-measurement-20261017` 测量成果、并在 `research/rt-a0-coordination-20261017` 分支归档的阶段性研究结果。研究主线依据仓库根目录的 `论文提要.md`，当前选择方向 A：中断服务与 vCPU 调度协同。

## 当前里程碑

1. 阶段一测量链已经完成：Guest ISR 时间戳、Host/Guest 计数器校准、IRQ 到 vCPU Ready/Running/Guest ISR 的有界追踪，以及 CPU/内存/Linux 负载夹具均已接入 `axvm::tests::vcpu_runtime`。
2. QEMU 证据确认了一个可构造、可复现的耦合点：FIFO vCPU 的 deferred IRQ service worker 使用默认 Fair 等级时，会被 CPU0 上的低等级 FIFO 阻挡任务延迟；服务等级继承可改变该调度顺序。
3. 阶段二最小原型已合入当前分支：`off`、`inherit`、`bounded` 三态。默认生产构建不启用；测试资源在 VM 创建前选择，配置只允许设置一次，停止和清理路径不改变。
4. 阶段三暂不扩展为 Deadline 协同。现有原型只证明调度顺序和固定窗口派发限制，尚未证明真实负载收益或论文创新。

## 复现实验

```sh
# 原始测量基线
VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD=baseline \
VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=off VIRQ_SAMPLES=600 \
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml

# 调度顺序 witness：只用于证明服务等级顺序
VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD=baseline \
VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=inherit \
VIRQ_INVERSION_WITNESS=1 VIRQ_SAMPLES=32 \
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml

# 派发上限：需要独立时间跨度检查确认确实发生等待
VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD=baseline \
VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=bounded \
VIRQ_IRQ_SERVICE_ROUNDS=8 VIRQ_IRQ_SERVICE_WINDOW_US=50000 \
VIRQ_SAMPLES=128 \
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml
```

离线分析：

```sh
python3 virtualization/axvm/tests/analysis/analyze_virq_irq_service.py \
  run.log --output-dir results
python3 virtualization/axvm/tests/analysis/analyze_virq_irq_service.py \
  run.log --require-throttle --output-dir throttle-results
```

## 归档布局

- `design/`：阶段判断、A0 设计和适用边界。
- `patches/`：研究补丁、来源校验和故障恢复验证。
- `configs/`：本轮 QEMU/构建输入的快照。
- `raw/`：原始 QEMU 日志及对应二进制身份 JSON，`SHA256SUMS` 为校验清单。
- `results/`：分析器 stdout 和校验清单。

QEMU 数据只证明功能、测量协议和调度顺序 witness。它不能替代 RK3588 等真板的性能证据，也不能作为 WCET/WCRT 或硬实时保证。所有样本仍须保留 ISR 校准区间、入口来源、Ready 关联状态和追踪丢失状态；不得把 1 ms mailbox 轮询确认时间当作 ISR 时延。
