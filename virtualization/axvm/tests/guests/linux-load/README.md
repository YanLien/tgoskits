# Linux 干扰 Guest 固定输入

本目录的 prepare.py 编译可校验 CPU 或内存工作负载，并生成供 vcpu_runtime 测例使用的独立 Linux VM。Linux 与实时 Guest 共用一个 VmManager，负载进度和最终停止由 support/linux.rs 验证；工作负载不访问实时 Guest 的 RAM。

## 1. 输入与构建

构建采用固定内核 SHA 和可选的固定基底配置，不接受任意摘要覆盖。镜像工具先校验注册包，prepare.py 再校验解包后的实际文件。

### 1.1 注册包配置

首次恢复环境时，在仓库根目录取得固定版本：

```sh
cargo xtask image pull qemu-aarch64:0.0.14 \
  -D target/research-assets/downloads -E target/research-assets/images
cargo xtask image pull initramfs-aarch64-busybox.cpio.gz:0.0.14 \
  -D target/research-assets/downloads -E target/research-assets/images
```

legacy 为默认基底，保持历史 SHA f71e2d9d...；registry-v0.0.14 采用 SHA a6fe2ed7... 的注册基底。后者只复制其中 bin/busybox，创建 proc/sys/dev/tmp，再加入源码编译的 ordinary-load 与 init。它不会复制注册包的 Guest 镜像、设备节点或符号链接，不需要挂载实体磁盘。不能将新基底运行与旧日志直接并入同一性能队列。

### 1.2 工具链分离

VIRQ_LINUX_CC 必须是 Linux 用户态交叉编译器的绝对路径，例如 /usr/bin/aarch64-linux-gnu-gcc；未提供时保留原 CROSS_COMPILE+gcc。Zephyr 则继续使用 virq/prepare.py 固定的裸机工具链，避免系统 GCC 的 libgcc 与裸机运行期不兼容。生成的 linux/build.json 记录编译器版本、完整命令、基底配置、内核和输入输出 SHA。

## 2. 双 VM 运行

标准 ktest 入口负责准备两个 Guest、打包宿主 initramfs 和最终判断，不在准备脚本内自行启动 QEMU 或断言运行成功。

### 2.1 运行入口

在仓库根目录用独立用户态编译器和明确的基底配置运行，环境变量中的镜像路径应为绝对路径：

```sh
VIRQ_TASK=1 VIRQ_TASK_DEADLINE_US=10000 VIRQ_SAMPLES=32 \
VIRQ_SOURCE=pl031_spi VIRQ_HOST_LOAD=linux_cpu \
VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=off \
VIRQ_LINUX_BASE_PROFILE=registry-v0.0.14 \
VIRQ_LINUX_CC=/usr/bin/aarch64-linux-gnu-gcc \
VIRQ_LINUX_KERNEL="$PWD/target/research-assets/images/qemu-aarch64/linux/linux-qemu" \
VIRQ_LINUX_INITRAMFS_BASE="$PWD/target/research-assets/images/initramfs-aarch64-busybox.cpio.gz/initramfs-aarch64-busybox.cpio.gz" \
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/linux/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/linux/qemu-aarch64.toml
```

Host 具有四个 pCPU：控制与 PL031 源/服务在 CPU0，实时目标在 CPU1，Linux 单 vCPU 默认位于 CPU3，Guest 逻辑 CPU 为 0。硬件源是此 QEMU 夹具的 Host-owned SPI34，再转发到实时 Guest vector48；不能据此认定已实现真实非关键中断压力 A。

`VIRQ_LINUX_HOST_CPU` 仅接受 1 或 3，默认 3。设为 1 时，必须同时使用 `VIRQ_EXPLICIT_DTB=1`、`VIRQ_TASK=1`、`VIRQ_TASK_WAIT=blocked`、当前 EL 物理中断源、Linux 双 VM 场景及 CPU0 服务。`guest_firmware.linux_host_cpu()` 统一选择，`prepare.py` 保持 Guest CPU0 并输出 Host 掩码 `1 << cpu`、构建元数据和 Host 资源；`support/linux.rs::Progress::start()` 核对 vCPU 配置掩码，离线分析再核对实际线程代际的运行与退休 CPU。设回 3 可恢复独立核配置。共享与独立配置须使用不同运行身份，不能混入同一个固定拓扑的性能队列；配置生成成功也不代表真板共享运行已经验证。

`analyze_virq_load.validate_linux()` 按同 CPU 的 ticks/sequence 验证启动 Running→Binding→GuestEntryBoundary→最终 Stopped，并要求每策略唯一代际覆盖各自 Host 围栏窗口。无围栏的完整旧日志从计划释放或提交覆盖到 Host 任务完成观察；无任务旧日志使用 ISR 观察，缺少 Host 时间依据则拒绝。runtime 记录可集中输出，不能用日志行位置代替策略时间窗，也不要求持续运行的代际在窗口内重新产生 Running 边界。

### 2.2 结果边界

workload.c 每批执行 8192 次 LCG，256 批报告一次；Host 独立校验递增计数、计算结果、CPU 身份、生命周期和 VM 停止。linux_cpu 提供 CPU 对照；计数是串口观察到的粗粒度工作量，不能充当精确 DRAM 流量或逐任务吞吐。T6 任务 Deadline 为 Host submit 起算的独立预算。

QEMU 只验证双 VM、跨层测量和清理功能。周期释放、独立 IRQ 压力、追踪开销、真板内存压力及频率/温度控制、重复四组实验仍须完成。

如需同时验证新的 Ready/Running 唤醒路径，在上述命令增加 VIRQ_TASK_WAIT=blocked。该模式允许并记录 Guest 后台核活动，不能声称非目标核静止；缺少新切换的事件仍保留 running_no_new_switch 状态。当前组合验证的每策略 32 条记录中，Fair 为 28 条、FIFO 为 32 条完整唤醒关联，全部 64 条均有有效 ISR→T6。

## 3. 内存压力 B

将上述命令中的 VIRQ_HOST_LOAD 改为 linux_memory，增加 VIRQ_LINUX_MEMORY_BYTES=16777216 与 VIRQ_LINUX_MEMORY_EVERY=1，即在相同 Linux vCPU 上保留 LCG，并每批顺序读改写 8192 个 u64。工作集范围 1～64 MiB、8192 字节对齐；every 范围 1～1024，表示每多少个 CPU 批次访问一次内存。默认值分别为 16 MiB、1。它调节相对访问频度，不保证固定 MB/s。

数组初始化不计入进度。每次读值与 index+已完成轮数比较，写值加一，并累加写值校验和。完整进度行同时发布 LCG 和内存批数、逻辑字节数及校验和，避免两条记录的观察偏移。Host 与离线分析独立重算结果，并拒绝缺少声明、混合模式或计数不一致。逻辑读写量分别为 memory_batches×8192×8；它们不是缓存行事务或 DRAM 流量。采样窗口允许观察进度为零。

选择 linux_cpu 可回滚到不分配数组的 CPU 对照，保留原进度格式。后续四组应将该 CPU 对照定义为 B0、数组流量定义为 B1，并保持两者拓扑相同。原生验证不能替代 QEMU，QEMU 不能替代真板性能证据。

## 4. 独立中断压力 A

在第 2.1 节入口中设 VIRQ_TASK_WAIT=blocked，并增加 VIRQ_IRQ_PRESSURE=sgi、VIRQ_IRQ_PRESSURE_PERIOD_US=2000、VIRQ_IRQ_PRESSURE_BURST=2，可同时测试非关键 SGI15 与关键 PL031 SPI34。选择 linux_memory 可同时接入 B；选择 linux_cpu 保持 CPU 对照。该压力源目前只接受四核 QEMU virt、current_el、CPU0 服务和阻塞任务，不改变系统 SGI0 或调度器定时器。

irq_pressure.rs::Pressure 独占申请 IRQ、由 CPU2 定期发送到 CPU0，并逐次确认完成。周期范围 100～1000000 us，批次范围 1～8；默认 off，开启后默认周期 2000 us、批次 2。4096 次上限、处理超时、错误 CPU/INTID 或回收失败均使实验失败。实际速率由 Host 时间窗口和确认次数计算，不能直接以请求周期当成已实现频率。

VIRQ_IRQ_PRESSURE=off 关闭 A，保留同一 Linux/实时 Guest 配置。VIRQ_IRQ_PRESSURE_EVENT/SUMMARY 和 analyze_virq_irq_pressure.py 核对每条发送、处理、已知答案和停止；verify_window() 校验压力和关键链使用同一计数频率且覆盖完整任务观察窗口。SGI 是合成 GIC 压力，仍需生产设备 IRQ 和真板实验；时间重叠不是因果证明。

## 5. 周期计划与排队

periodic.rs 将固定计划释放与任务完成解耦，供双 VM 夹具观察跨周期积压。它保留每次物理 IRQ 的 ISR 确认，记录实际迟到，不宣称外部设备已经按计划时刻触发。

### 5.1 启用与回滚

在第 2.1 节入口设置 VIRQ_TASK_WAIT=blocked、VIRQ_PERIOD_US=250、VIRQ_TASK_ROUNDS=1048576，可运行强工作量的周期配置。周期范围 100～1000000 us，轮数范围 4096～1048576；仍需 current_el、PL031 SPI 与 CPU0 服务。低工作量功能配置可用 20000 us/4096 轮。设置 VIRQ_PERIOD_US=0、VIRQ_TASK_ROUNDS=4096 回到原逐项等待完成的模式。

研究归档内的 run-periodic.sh 也可选择完整配置，必须使用新运行名保护已有日志。例如在仓库根目录运行：

```sh
sh research/cross-path-20261017/run-periodic.sh my-periodic-run 250 1048576 off linux_memory 32
```

脚本的周期模式默认每策略 32 项，关闭模式默认 128 项，也可用第六参数显式指定；短于完整 Linux 进度报告间隔的观察窗口可能被原进度断言拒绝。样本上限仍为 1000。较长计划需要相应的 QEMU 超时预算；脚本不自动丢弃迟到任务，也不为等待 Linux 进度而延长定义好的采样区间。

### 5.2 观察语义

Guest 计数信号量保存每次 ISR 的任务通知，Host 在全部完成后的完整排空行之后批量读取结果。周期扩展独立校验版本和工作量，避免把低字节回绕误当全队列完成。

```mermaid
flowchart LR
    P[固定计划到达] --> H[Host 待投递队列]
    H -->|一个未确认 ISR| I[SPI34 到 Guest48]
    I --> Q[计数信号量]
    Q --> T[Guest 单线程任务]
    T --> D[排空后批量确认]
```

analyze_virq_periodic.py 独立重算固定网格、Host 到期积压和 Guest outstanding。周期 Deadline 从计划到达起算，包含迟到、排队与执行；submit→T6 仍单独保留。批量 Host observed 时间不是各项实际 T6，任务时间仍来自 Guest counter 校准。开启 A 时还要确认压力覆盖计划到达→完成观察的完整区间。
