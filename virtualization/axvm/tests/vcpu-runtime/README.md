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

## 6. 有界运行路径追踪

AArch64 的 `axtest` 配置提供 `axvm::diagnostics` 观测接口；默认生产构建整体移除模块与插桩点。本测例在 Guest 启动前一次性初始化每 CPU 16384 槽的缓冲区，两个 CPU 的槽载荷约 1.25 MiB，不在热路径分配、打印或取得任务/rq 锁。槽只追加不覆盖；冻结门、在途写入计数和 release/acquire 提交协议保证快照完整性。容量耗尽或未提交记录使测试失败。

`VIRQ_RUNTIME` 导出 CPU、每 CPU 连续序号、宿主物理计数、事件类别、带代际的线程 ID 及两个事件载荷；Binding 的载荷为 VM ID/vCPU ID。事件包括 IrqKick、WakeBegin/End、Running/Stopped 和 GuestEntryBoundary。切入/切出复用既有线程扩展回调；Entry 位于 VGIC bank load 后与低层 run 之前，仍包含寄存器恢复开销。WakeEnd 可能晚于远端 Running，它不是精确就绪队列发布时间。

所有 VM 及线程清理完成后才冻结并输出追踪；`VIRQ_RUNTIME_SUMMARY` 的记录总数、dropped 和 incomplete 必须与导出一致。另有 128 条 `VIRQ_TRACE_ENVELOPE` 测量 Marker 调用与两端计时的整体包络，包括可能的抢占，不是所有插桩点的纯执行成本或硬实时上界。缺失切入、目标已运行、时钟区间内事件以及多事件歧义必须保留，不能拼接为有利的串行样本。

新增 Ready/enqueue 队列边界见第 7 节。QEMU 仅验证关联和失败传播；其他板卡 axtest 目标中的插桩门默认关闭，但其性能影响仍需真板复核，不能从本测例推断已无影响。

## 7. 调度队列 Ready 观测

`ax-task` 在 `cfg(axtest)` 下提供一次安装、禁止替换的 `ReadyTraceHook`，在直接唤醒入队、on-rq 恢复和 owner 入队的状态更新后、释放队列锁前调用。AxVM 通过既有线程扩展 ops 身份过滤 vCPU，不新建线程登记表；回调只进行身份比较、计数器读取和有界原子写入，不取得任务/rq 锁，不分配或通知。默认生产构建移除调度插桩。`cargo xtask ktest` 会统一提供该 cfg。

`ReadyEnqueue` 的 thread 为带代际的目标线程，value0 为目标 CPU，value1 的低 8 位是路径原因（1 DirectWake、2 OnRunQueueWake、3 OwnerWake、4 OwnerYield、5 OwnerPreempted、6 OwnerReplenished、7 OwnerMigrated、8 OwnerPolicyChanged），第 8 位表示更新前仍占用 CPU。观察 CPU 可以不同于目标 CPU。on_cpu、迁移、让出或策略变化不能直接当成一次新的 wake-to-run 等待。

这是队列锁内的软件入队边界，不是物理 CPU 已开始执行，也不是纯调度策略排队时长；Ready 到 Running 包含后续提交、锁释放和调度。Deadline 仍被 throttled 的早退不记为 Ready。

`VIRQ_READY_SUMMARY` 给出事件数量，缺少 Ready 记录会让测例失败。测例还验证试图替换已安装观察者会被拒绝；完整运行继续验证原观察者真实产出事件。离线必须按线程代际、样本窗口、路径、on_cpu 与目标 CPU 关联，保留歧义和缺失样本。


## 8. 采样区间同核 CPU 负载

默认生成的 fixture 为 baseline。运行同一 ktest 命令时设置
`VIRQ_HOST_LOAD=cpu_same_core`，准备脚本将场景写入资源文件，非法值报错。
控制线程固定 CPU0；负载线程在 VM 启动前绑定 CPU1，完成首批工作后阻塞。
前校准完成且 CLOCK_START 发布后才启用连续计算，每批8192次整数递推并主动 yield。
负载的完整所有者位于 with_vm 外：VM 正常/错误清理结束后才 stop 和 join，
避免 FIFO Guest 忙等阶段压制较低优先级线程导致启停互等。

VIRQ_LOAD_SAMPLE 保留每条 submit→确认观察窗口内的批次计数；
VIRQ_LOAD_SUMMARY 保留区间与最终批次、线程身份、错核次数、checksum 及 joined。
单条窗口无工作进展仍保留；整个采样区间无进展或错核会使测试失败。
统计并不证明该工作先于 ISR，也不代表恒定 CPU 利用率。
所有事件在采样后打印；setup 定位标记不会进入测量区间。
默认 baseline 不创建负载，同样固定控制线程，便于同版本对照。

这是宿主负载的测量验证，不能代替普通 VM 干扰或真板性能证据。
设置 `VIRQ_HOST_LOAD=cpu_continuous` 时，在 VM 启动前启用持续计算，
额外输出每策略的 VIRQ_LOAD_BOOT_WORK 批次，保留启动期和采样期的不同窗口。
三种场景均须显式记录，不能把门控负载日志重标为持续负载。

持续负载曾使 FIFO VM 启动停顿。现场确认是宿主 counted-wake 循环反复
notify_one，在每次释放抢占保护后重复选中已经重新等待的高优先级 vCPU；
控制 owner 因而无法完成 admission 打开。WaitQueue 现按通知开始时的登记序号
上界限制选择范围，ArceOS API 复用 notify_n；原来的持续负载场景和通用
wait-queue 重入回归均已通过。精确 ELF、旧现场和修复证据由研究记录归档。
这个正确性修复不构成论文优化收益，队列广播批次自身的有界成本仍需计量。


## 9. CNTP 物理 PPI 路径

默认 `VIRQ_SOURCE=software` 保留原软件 edge；设置
`VIRQ_SOURCE=physical_timer_ppi` 使用 QEMU virt 的 CPU0 CNTP 比较器和 PPI30。
本机器 FDT 的 timer interrupts 第1项（从0计数）为 PPI14，即 INTID30；
它必须与宿主 clockevent 不同，且硬件 CNTP 未启用，才允许独占注册。
这份固定QEMU夹具不能用作真板的源发现逻辑。

每次只编程一个约1ms后的deadline，等Guest确认再处理下一次；
handler先关闭源电平，再调用已有IRQ-safe port。所有资源在VM停止前
停止、disable/synchronize/free并恢复寄存器，错误返回也走同一守卫清理。
各策略输出 VIRQ_PHYSICAL_ARM 与 VIRQ_PHYSICAL_SUMMARY。

HostIrqEntry 的时间取自 HostGuestTrap::current_irq 回调开始，
在IAR之前；向量保存和axcpu构造InterruptedContext的包装代码已经执行。
当前实验要求600条该current-EL路径记录，不能补造缺失入口。
它是内部物理PPI，不代表外设SPI、引脚到达时间或Guest-running低EL入口。

VIRQ_SOURCE 明确区分日志来源。兼容日志中的pulse_ns在物理模式表示宿主
arm提交耗时，分析器改名timer_arm_ns；submit到ISR亦改名timer_arm_to_c_isr。
真正的回调入口到ISR区间需通过物理分析器关联入口和独立时钟校准后取得，
不能把编程的1ms或确认轮询当作该区间。


## 10. 三CPU跨核内存工作集

使用同目录 build-aarch64-memory.toml 与 qemu-aarch64-memory.toml，
设置 VIRQ_HOST_LOAD=memory_cross_core，VIRQ_MEMORY_BYTES 为字节数
（默认16777216，范围1–64MiB，8192字节对齐）。源仍由VIRQ_SOURCE独立选择。
普通两CPU配置会明确拒绝不可用的CPU2；三CPU baseline使用同一配置但不创建负载。

控制与物理源在CPU0、目标vCPU在CPU1、内存worker固定CPU2。既有contention
启停/join协议同时承载计算和内存两种具体工作，不改生产调度策略。
私有工作集初始化word[i]=i，每批1024个u64各做一次volatile读/加一/写，
分批yield；完成批次才更新计数。停止后逐word检查完整循环与剩余chunk，
输出VIRQ_MEMORY_SUMMARY的逻辑读写字节、checksum、verified_words和joined。
内存不与其他任务、Guest或DMA共享，错误更新会使整个测例失败。

逻辑字节不等于缓存行填充、DRAM访问或PMU事件；初始化与最终验证不计入循环流量，
窗口边界还可能横跨未完成chunk。signal worker和管理任务仍可能使用CPU2，
因此该场景不能宣称纯带宽干扰。QEMU只验证功能，真实缓存容量、拓扑、
PMU归属与板卡性能需要独立测量。


## 11. 宿主服务亲和性

用 VIRQ_SERVICE_PLACEMENT=cpu0 在任何 VM 创建前固定 control 与 run signal worker 到 CPU0，避免它们在 CPU2 与内存 worker 调度竞争。缺省 unrestricted 保留原线程放置。两种模式必须使用同版本及相同 CPU 数比较；控制两个服务不等于隔离所有宿主活动，也不提供真实 DRAM 干扰证据。

本配置只编译到 AArch64 axtest。沿用 ThreadBuilder affinity，在 prepare/spawn 前设置，原有 extension、发布/激活和 stop/join 协议保持原流程。局部 probe 在任务进入、工作迭代和退出观察 CPU；销毁/join 后校验每个角色的 started/finished、observations 与 wrong_cpu，错核导致整套失败。输出 VIRQ_SERVICE_PLACEMENT、逐线程 VIRQ_SERVICE_THREAD 及汇总 VIRQ_SERVICE_SUMMARY；原子汇总只在退出时更新，热循环不打印。

物理 PPI 对照与内存场景均可在第10节命令增加该环境变量。CPU0同时承担测量控制器和IRQ源，仍需记录该服务路径与测量开销；默认模式没有位置保证。配置不支持在VM运行中切换。


## 12. Guest执行期间的PPI

设置 VIRQ_IRQ_CONTEXT=guest_running、VIRQ_SERVICE_PLACEMENT=cpu2、VIRQ_HOST_LOAD=baseline 和 VIRQ_SOURCE=physical_timer_ppi，使用第10节的三宿主核build/QEMU配置。保留Guest映射[0,1]：控制器CPU0使用默认策略，目标Guest vCPU1在CPU1持续执行，control/signal服务固定CPU2。该组合接受baseline或memory_cross_core；后者使用CPU3内存worker，必须使用四宿主核配置。

复用mailbox offset28的保留word为running_mode，host在CLOCK_START前写入并用DMB发布，Guest acquire读取并以arch_nop代替采样期的PSCI suspend；大小仍2448字节，原时钟/ISR偏移不变。CPU1的CNTP/PPI30由CPU0控制者通过既有同步hard-call入口操作；请求存于调用者栈，回调有界、IRQ关闭、无分配且不保留指针。先独占disabled PPI，再确认bank未启用；结束先mask、disable/synchronize/free，再恢复原inactive bank和释放观察器，远程恢复失败时保留原状态供清理重试。

ax-cpu的可选virtualization-trace特性在低EL IRQ保存GPR后、读取IAR前采样CNTPCT，经Exit交还已恢复的宿主上下文。AxVM axtest启用该特性；生产默认不含该字段或读写指令。HostIrqEntry.value1=2表示低EL汇编点，1仍表示current-EL回调（保存GPR及Rust上下文包装后、IAR前）。事件原点逐样本保留；current-EL事件不会被删除以伪造全部Guest执行期间中断。

默认VIRQ_IRQ_CONTEXT=current_el保留CPU0源到CPU1挂起目标的原夹具。两种条件的源CPU和Guest运行状态不同，不可将时延差异直接当作策略收益；均不是外设引脚到达、向量第一指令或真板性能证据。新增向量读时钟开销仍需实板审计。静态检查共享同一Cargo目录时串行执行，避免不同目标构建的future-incompatibility报告交错。


## 13. 低EL与持续内存工作集组合

使用 build-aarch64-memory-running.toml 和 qemu-aarch64-memory-running.toml，保持四宿主CPU，并设置 VIRQ_IRQ_CONTEXT=guest_running、VIRQ_SERVICE_PLACEMENT=cpu2、VIRQ_SOURCE=physical_timer_ppi。VIRQ_HOST_LOAD 分别设置 baseline 与 memory_cross_core 形成同拓扑对照；内存大小仍由 VIRQ_MEMORY_BYTES 控制。

CPU0控制、CPU1源/Guest目标、CPU2服务、CPU3内存工作集。内存CPU由IRQ上下文派生并打印在VIRQ_MEMORY_CONFIG/SUMMARY，current_el原场景仍使用CPU2；普通三核配置运行组合会明确拒绝不可用CPU3，不能退回服务核。复用原stop/join与全量word校验，不增加共享缓冲区。两个指定服务与内存worker分核不意味着隔离全部宿主活动；QEMU数据仍不证明DRAM干扰或机制收益。


## 14. Host-owned PL031 SPI source

设置 VIRQ_SOURCE=pl031_spi、VIRQ_IRQ_CONTEXT=current_el、VIRQ_SERVICE_PLACEMENT=cpu0、VIRQ_HOST_LOAD=baseline，使用原双核build/QEMU配置。准备脚本检查实际Guest构建未启用RTC/counter；运行期禁止Guest passthrough并核对FDT及PL031标识。宿主独占SPI34，以现有RTC驱动编程当前秒的match，在ISR内mask/clear后发布虚拟vector48到CPU1目标。这是QEMU特定的Host-owned设备源，不是assigned-SPI直通、真实引脚或周期吞吐基准。

两个新增驱动只读方法用于MR/IMSC准入及恢复读回。单一Rtc对象存于IRQ-safe寄存器bank；任务先disable精确IRQ再持锁，callback释放bank后才发布Guest通知。结束disable、mask/clear、synchronize/free，再恢复MR0/IMSC0并释放观察器与Rtc；清理失败隔离借用标记而不发布别名。永久Device映射通过ax-mm iomap取得，不由此测试撤销。

VIRQ_RTC_CONFIG、逐样本VIRQ_RTC_ARM match_seconds及VIRQ_RTC_SUMMARY明确设备、计数、源退休及寄存器状态。RTC秒计数没有Host due_ticks含义。既有VIRQ_HOST_SAMPLE pulse_ns字段在此模式由分析器重命名rtc_arm_ns；入口来自current-EL保存GPR及Rust包装后/IAR前，并不是物理信号到达时间。必须保留全部ISR样本与Ready状态；QEMU功能通过不支持真板性能或硬实时结论。


## 15. 有界采样规模

`VIRQ_SAMPLES` 可设为1..1000的整数，默认300，单位是每策略的中断响应条数。prepare以该输入编译Guest尾部ISR数组，校验实际ELF mailbox大小，并生成Host的samples字段；READY/COMPLETE、Host统计和设备注销计数必须一致。启动时输出唯一的 `VIRQ_MEASUREMENT samples_per_policy=N`。Host在READY完整行核对规模后才投递，拒绝陈旧或混配资源。

已有300条历史日志没有新声明，分析器仍按300验证；新规模必须有明确声明，不能从实际行数推断预期数。声明重复、越界、缺样本或源汇总计数不匹配均失败。每CPU追踪仍为16384条；允许配置1000不保证任意负载都能容纳，溢出使整个测例失败。扩展采集采用独立boot分批，保留每次原始日志、校准、二进制及退出状态；不在活跃写者存在时清空缓冲，不把多boot直接当IID样本合并，也不把样本最大值称为WCET。

```sh
VIRQ_SAMPLES=500 VIRQ_SOURCE=pl031_spi VIRQ_SERVICE_PLACEMENT=cpu0 \
  cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml
```


## 16. 普通Linux VM计算场景

`VIRQ_HOST_LOAD=linux_cpu`使用同一VmManager同时拥有Linux VM1与实时VM2，控制/源/服务CPU0、实时目标CPU1、Linux单vCPU固定CPU3；Linux使用virtualized、分配RAM和空passthrough，用户程序有连续批次/checksum协议。使用`vcpu-runtime/linux/`下的四核8GiB build/QEMU/资源配置，并显式提供已校验的VIRQ_LINUX_KERNEL和VIRQ_LINUX_INITRAMFS_BASE路径。默认单VM资源配置不捆绑Linux。

Guest逻辑CPU0不是Host CPU0。Linux串口进度在实时计时窗外排空，按8192次/批、256批/报告核验，不能作精确DRAM流量或单条ISR内的工作计数。采样与后校准后以Host stop停止Linux，再导出实时数据；全部服务销毁/join后才freeze。保留有界追踪和溢出失败，不把QEMU通过当作实板瓶颈或吞吐收益。


A0仅在AArch64 axtest启用：VIRQ_IRQ_SERVICE=off/inherit/bounded。后两态对FIFO目标继承其等级，bounded限制每run的worker派发轮数；VIRQ_IRQ_SERVICE_ROUNDS范围1..256、VIRQ_IRQ_SERVICE_WINDOW_US范围100..100000，默认8轮/1ms。该限额不是IRQ数量、CPU执行预算、滑动窗口保证或Deadline感知算法。VIRQ_IRQ_SERVICE与VIRQ_IRQ_SERVICE_JOIN记录实际base策略和join结果。VIRQ_INVERSION_WITNESS=1仅用于baseline/current-EL/PPI/CPU0服务的有限FIFO60阻挡判定，禁止混入普通性能分布。50ms限额压力配置也单列分析。
