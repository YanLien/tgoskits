# IRQ测量的离线分析

本目录分析原生vcpu_runtime日志，保留所有样本及无法完整分解的状态。它不把宿主确认轮询时间当作Guest ISR时延，不把QEMU结果解释为实板性能或硬实时保证。

在仓库根目录运行现有测例，例如已经验证的current-EL物理PPI配置：

```sh
VIRQ_SOURCE=physical_timer_ppi VIRQ_SERVICE_PLACEMENT=cpu0 \
VIRQ_HOST_LOAD=baseline VIRQ_SAMPLES=128 \
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml \
  > run.log 2>&1

python3 virtualization/axvm/tests/analysis/analyze_virq_physical.py \
  run.log --output-dir results
```

Guest构建按tests/guests/virq/prepare.py固定上游提交、工具链与样本协议；可设置CROSS_COMPILE、VIRQ_CACHE_DIR、CARGO_TARGET_DIR。Linux双Guest还要求固定kernel与BusyBox基底，具体SHA和输入环境见tests/guests/linux-load/prepare.py。更换镜像不能继续沿用此前性能结论。

分析器会校验前后校准区间相交、计数器频率、唯一物理入口与样本关联、Ready与运行代际、服务亲和性、源注销、工作量checksum和追踪丢失。运行探针对照需使用对应probe分支的配置；未编译、关闭采集与开启采集是不同状态，关闭采集不等于无插桩。

```sh
python3 -m unittest discover -s virtualization/axvm/tests/analysis -p 'test_virq_*.py'
python3 virtualization/axvm/tests/analysis/audit_virq_tail.py --help
```

有界缓冲区溢出使整组失败。每策略300条时P99.9等于最大观测值，不能据此声称尾部估计精度、WCET或WCRT。多boot和累计样本量也不自动证明IID。logical read/write计数不当作DRAM流量；Linux串口进度不当作精确ISR重叠工作量。

原始日志、现场二进制、SHA和补丁另行归档；本目录提交可复用分析代码及其通用行为测试。A0机制分支还提供IRQ服务调度顺序与限额的独立分析入口。
