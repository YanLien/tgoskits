# 双 vCPU 运行时测例资源

本目录保存 `axvm` 包 `vcpu_runtime` ktest 测例的构建、运行与资源装载约定。这里的内容只回答“宿主用哪份配置构建、QEMU 以什么形态启动、客户机与夹具如何进入宿主内存根”，不复制客户机算法，也不包含判定逻辑：判定由 `axvm` 的 axtest 目标与 ktest 的成功标记完成。

## 1. 测例配置

四个配置文件分工明确：`build-aarch64-unknown-none-softfloat.toml` 描述宿主内核构建，`qemu-aarch64.toml` 描述 QEMU 平台参数与超时，`guest-builds.toml` 声明运行前必须执行的资源准备，`host-initramfs.toml` 把准备好的资源与 VM 描述装进宿主内存根。

| 文件 | 关键内容 | 作用 |
| --- | --- | --- |
| `build-aarch64-unknown-none-softfloat.toml` | `features = []`、`max_cpu_num = 2`、`target = "aarch64-unknown-none-softfloat"` | 提供两个宿主 CPU 与裸机目标；不开启任何产品功能特性 |
| `qemu-aarch64.toml` | `-smp 2`、`virt,virtualization=on,gic-version=3`、`to_bin = true`、`timeout = 900` | 双 vCPU 运行环境、GICv3 虚拟化与整次运行的时限 |
| `guest-builds.toml` | `arceos_build_configs = []`、`host_prepare = [...]` | 声明本测例的客户机不是 ArceOS，而是由准备脚本生成的 Zephyr 客户机 |
| `host-initramfs.toml` | `source`、`vm_configs` | 指定宿主内存根夹具目录与被打包的 VM 描述 |

这四个文件由 `cargo xtask ktest qemu` 的 `--config` 与 `--qemu-config` 直接消费，因此它们既是本地手工运行的输入，也是 CI 作业的唯一配置来源。

### 1.1 宿主构建配置

`features = []` 表示本测例不为运行时准备行为开启任何专用特性：测试目标需要的 feature 由它自己的 `required-features` 与 ktest 的 `axtest` 特性共同决定，客户机资源则由 `guest-builds.toml` 的 `host_prepare` 生成。`max_cpu_num = 2` 与 QEMU 的 `-smp 2` 一致，保证两个 vCPU 各有一个宿主 CPU 可用；把 vCPU 压到一个宿主核上会改变本测例要验证的唤醒路径。

### 1.2 QEMU 运行配置

`qemu-aarch64.toml` 保持历史双 vCPU 平台参数，并且是显式无盘配置：`args` 里没有宿主根盘，也没有 `root=`，宿主直接从内存根启动客户机，客户机镜像来自 `/guest/builtin/images`。`timeout = 900` 保留旧流程“构建与运行合计不超过 900 秒”的预算；成功与否不由该文件判定，`fail_regex` 里的客户机失败标记与 `panicked at` 只是提前中止的护栏。

## 2. 资源装载

`host_prepare` 的约定是：以仓库根为工作目录、带上 `AXBUILD_TARGET_DIR` 环境变量执行 `python3 virtualization/axvm/tests/guests/virq/prepare.py`。脚本据此把客户机镜像、`vm.toml` 与 `resources/tests/vcpu-runtime.toml` 写进 `<target>/axbuild/axvm/vcpu-runtime`，供后续的打包与运行阶段读取；它不构建宿主内核，也不启动 QEMU。

`host-initramfs.toml` 的 `source` 指向同一输出目录下的 `resources`，于是夹具以 `/tests/vcpu-runtime.toml` 出现在宿主内存根；`vm_configs` 指向生成的 `vm.toml`，打包时它的启动资源路径会被改写为 `/guest/builtin/images/<摘要>`，配置本体落在 `/guest/builtin/configs/vm-2.toml`。`BOOT_IMAGE_PATH_FIELDS` 覆盖 `kernel_path`、`dtb_path`、`bios_path`、`uefi_firmware_path`、`ramdisk_path`，因此测试目标只需读这两个稳定路径，不需要知道镜像摘要。

### 2.1 地址约定

`/tests/vcpu-runtime.toml` 的 `entry` 与 `mailbox` 由准备脚本从 ELF 读取后写入，永不手工填写；宿主测试目标用 `entry` 校验客户机实际入口、用 `mailbox` 读取投递计数与挂起次数，从而把“资源是否与当前镜像匹配”变成运行期可检查的事实，而不是注释里的承诺。

### 2.2 同一内核内的多个 vCPU

本测例的两个 vCPU 由同一个宿主内核、在同一次启动内创建并运行：它们共享内核的调度器、GIC 与内存映射，因此“向 vCPU1 投递中断不会让 vCPU0 离开挂起”才是一个可验证的内核内不变量。这与“同一架构上启动多个独立系统用例”不同——后者只是复用同一份内核镜像与同一套构建特性，每个用例仍然独立启动自己的内核实例。

## 3. 入口与判定

本地与 CI 共用同一条命令：`cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml`。它要求 `axvm` 包在 `virtualization/axvm/Cargo.toml` 中声明 `[package.metadata.axtest] runtime = "axvisor"`、`[package.metadata.axtest].target_triples` 中的 AArch64 目标，以及 `harness = false` 的 `[[test]] name = "vcpu_runtime"`；缺少任一项时 ktest 的发现阶段就会报错，而不是静默跳过。

运行器依次要求通过的 `AXTEST_CASE`、`fail=0` 且至少一个用例通过的 `AXTEST_SUMMARY`、最终 `AXTEST_SUITE_OK`。宿主内核的 `run_kernel_tests()` 在全部用例通过后打印最终标记并进入退出回调；失败时打印 `AXTEST_SUITE_FAIL`。测试目标必须在返回 case 结果前通过正常管理器释放客户机并等待任务退出。

### 3.1 运行代次与资源清理

宿主测试目标不直接持有 vCPU 后端，也不通过广播接口操作客户机：它用 `VmManager::create(VmCreatePlan)` 建立实例，再用绑定到具体运行代次的端口完成投递与读取。下表列出本测例依赖的公共入口及其语义。

| 入口 | 语义 |
| --- | --- |
| `VmManager::create(VmCreatePlan)` | 预留实例代次，等待操作完成后得到 `VmHandle`；机器初始化、镜像加载与 `Ready` 快照发布由控制任务完成 |
| `VmCreatePlan::vcpu_schedule_policy` | 应用于每个 vCPU 宿主任务的宿主调度策略；本测例在同一宿主启动内依次验证 Fair 与 FIFO(80)，不引入基准专用 feature |
| `VmHandle::start()` / `VmHandle::reset()` | 等待操作完成后得到新的 `RunId`（运行代次），每次运行都从同一条已发布配置重新开始 |
| `VmHandle::guest_memory(RunId)`、`VmHandle::interrupt_port(RunId, vcpu_id, vector)` | 只对当前运行代次有效的内存与中断端口；代次过期时返回 `StaleRun` 而不是猜测当前实例 |
| `VmHandle::destroy()` 的操作完成 | `destroy` 的完成由控制任务退出观察发布，是“控制任务已返回且资源已释放”的证据；随后才能收尾 |
| `VmManager::shutdown()` | 关闭管理器并等待登记实例退出，用于测试结束前确认没有遗留运行 |

因此“投递中断不会唤醒闲置 vCPU”这条不变量由运行代次内的端口表达：`interrupt_port()` 直接绑定目标 vCPU 与向量，测试不需要、也不应该用“给整个 VM 广播”来模拟定向投递；测试结束时先销毁实例、再等待控制任务退出，最后才让内核打印套件标记并退出。

### 3.2 在 CI 中的登记

`.github/ci/checks/axvisor.toml` 的 AArch64 QEMU 作业同时登记本测例：`package = "axvm"`、`test = "vcpu_runtime"`、`arch = "aarch64"` 以及上面两个配置文件路径。规划器会用这份登记校验包、测试目标与配置文件确实存在，并把改动这两个文件或其所在目录的拉取请求路由到同一个作业。

## 4. 宿主侧测量样本

测试在 Fair 和 FIFO(80) 下各记录 300 条 `VIRQ_HOST_SAMPLE`，字段为策略、从 1 开始的样本序号、`pulse_ns` 与 `ack_observed_ns`。前者测量宿主调用 `interrupt.pulse()` 的耗时；后者测量调用前至宿主观察到 Guest 确认计数的时间。两者使用同一宿主 `Instant` 时钟，单位为纳秒，样本缓存在测试任务中并在全部投递完成后输出，采样区间不打印样本。

`ack_observed_ns` 包含宿主控制台处理、Guest 内存读取、调度等待及最多多轮 1 ms 休眠轮询；它不是 ISR 时间戳，也不用于推导中断延迟或其上界。`pulse_ns` 也不代表目标 vCPU 已完成注入。采样序列只保证一个未确认投递，不保证每次投递前目标 vCPU 已重新挂起，因此不能把它称为纯唤醒延迟。QEMU 数据用于验证测量链路，不能替代真板实时性结论。300 个样本不足以稳定估计 P99.9；不添加性能通过门槛，正确性仍由原有投递、隔离、代次和清理断言判定。

## 5. Guest ISR 时间戳与时钟校准

每策略额外导出 300 条 `VIRQ_ISR_SAMPLE` 与 64 条 `VIRQ_CLOCK_SAMPLE`。ISR 在 C 函数开头以 ISB + CNTVCT + ISB 记录虚拟计数；宿主通过已有物理计数接口并追加 ISB 记录投递前与确认后的计数。CNTPCT 在当前 Guest 中被模拟，故不将它用作低开销探针。宿主还验证 Guest 与宿主频率相等且非零。

采样前后各 32 次独立请求—应答：宿主 H0 写请求，Guest 记录 G 后 release 发布确认，宿主观察后用 DMB 读取稳定载荷并记录 H1。恒定偏移 O 必须位于每个 [H0-G,H1-G] 区间的交集；空交集、超时、频率不符或 ISR 不在投递与确认的因果窗口内均失败。所有原始计数和频率在采样后输出，允许离线重新计算，不假定往返对称。

时钟校准仅检查有限观测区间的相容性，不证明永久同步、无漂移或硬实时上界。结果定位至 Guest C ISR，含 Guest 向量分发；插桩本身有开销。序列保持单个未确认中断，但不是每次投递前都确认目标已挂起。QEMU 仅验证协议，真板性能仍需单独测量。
