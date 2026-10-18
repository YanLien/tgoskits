# 跨路径干扰六阶段实验记录

本目录依据上级 `../../../论文提要.md` 的 V3.0 六阶段计划开展实验，继承旧归档的可复用测量工具，但以阶段 0～5 和 M1/M2/M3 作为验收依据。旧归档中的“四阶段”和 A0 调度 witness 不能代替新版的中断压力 A × 内存压力 B 实验。

当前已完成版本2记录操作的8/8对真板 on/off 对照，共1024条任务；同版本8次 on 启动的512条任务中，493条满足严格唯一阶段关联。正式0/A/B/AB恢复队列正按8个独立完整块、32次真板启动执行，进度以[恢复状态](results/factorial-recovery-status.json)为准，完整块收齐前不计算临时交互结论。[开销报告](results/recorder-ops-report.md)、[阶段基线](results/stage-baseline-report.md)及[阶段验收审计](results/phase01-requirements-audit.md)是当前证据；下文保留各历史检查点，新进展见[阶段0～2检查点](results/phase12-progress.md)。第二种双VM拓扑在独立工作区验证，不改运行中的冻结输入。M1/M2尚未正式通过，没有稳定交互、机制或联合优化收益结论。

## 1. 当前证据

当前检查在远端 `10.3.10.72` 的实际工作树执行；未提交修改保留，尚未新增联合控制实现。

### 1.1 平台采集

通过 `ostool board connect -b BallPick-Robot --server http://10.3.10.60:2999` 成功分配板卡并进入自动登录的 Linux 串口。连接会触发板卡启动，未刷写存储。串口确认 Orange Pi 5 Plus、RK3588、16 GiB、U-Boot 2025.04 和 BL31 v2.12.0。原始终端输出位于 `raw/board-*.txt`；ANSI 转义、命令回显和错误均保留。

Linux 6.1.99 暴露 Cortex-A55 CPU0～3、Cortex-A76 CPU4～7、共享 3 MiB L3，以及 `armv8_pmuv3` 事件源。三个 cpufreq policy 均为 ondemand，采样温度约 32.4°C，尚未固定频率。PMU sysfs 事件名称只证明驱动暴露事件编码，尚未证明计数可用、归属正确或调节带宽可行。没有 `perf` 可执行文件，`perf_event_paranoid=2`；`sudo -n` 需要密码。启动 DTB 文件已取得 SHA-256，运行时原始 FDT 受权限限制；经 `dtc` 重建的树单独标识，不能冒充原始 FDT 哈希。

`collect-linux-capabilities.sh` 提供同类只读采集命令，需在板卡 Linux 上运行。已有输出由本次串口命令采集，脚本不冒称已自动执行。Linux 中存在 IOMMU group、KVM 和 PMU 节点仍不能证明 AxVisor 中的硬件策略可用。

### 1.2 测量链核验

旧归档 `../rt-virtualization-20261017/verify_archive.sh` 在当前服务器通过：脚本语法、JSON、四组校验清单和 21 项分析测试。日志保存于 `raw/archive-verification.txt`。这证明已有工具和归档可以重用，不证明新版端到端要求已完成。

首次检查时，源码已增加 ISR 起止字段，但旧 QEMU 日志缺少终点。首次小规模运行使用系统 GCC13 Linux 交叉编译器，Guest 链接因 `__getauxval` 和 GNU 构造器要求失败，未进入 QEMU。随后改用准备脚本默认固定的 Arm 10.3-2021.07 裸机工具链复跑成功，Fair/FIFO 各 32 条样本均通过四类分析器；ISR 起止完整，runtime/Ready 各 32/32，3305 条追踪记录 dropped=0、incomplete=0。小规模样本只用于字段与关联验证，后续扩展见各检查点。

## 2. 阶段验收

实验必须从观测和受控负载出发；A0 的 off/inherit/bounded 是既有探索原型，当前不会据此跳过 RQ1/RQ2。

### 2.1 六阶段差距

下表中的“未完成”按 V3.0 验收标准判定，避免旧阶段名称造成误读。

| 阶段 | 已有依据 | 尚需完成 |
| --- | --- | --- |
| 0 平台与负载 | 真板双 VM 复位、CNTP 基线及首组 A+B 完整功能验收；Linux 能力快照 | 频率/温控/计数器固定；压力强度与混杂核实 |
| 1 时间链 | 真板基线及 A+B 的已定义时间链；记录器开关 4 块配对；QEMU 积压 | 实际 IRQ/计时器阶段；GuestEntryBoundary 含义；残余握手/时间戳成本；频温/固件证据及外部输出 |
| 2 交互识别 | 工作量、Deadline、完整性及吞吐的数据契约已作 QEMU 功能验证 | 真板同配置 E0/E1/E2/E3，重复与随机顺序；均值交互及区间；尾部、违约率、普通 VM 吞吐权衡 |
| 3 机制归因 | 既有调度 witness 可作线索 | 阶段 2 后的相位、资源和路径干预；跨周期证据 |
| 4 最小控制 | A0 探索原型可独立开关 | 以已证实机制选择控制；Deadline、频率、成本、资源保底与回退 |
| 5 论文评估 | 可复用归档和分析入口 | 真板匹配基线、单项/Joint/消融、不确定性、开销及吞吐权衡 |

阶段 0～2 优先。QEMU 只用于功能和数据契约，不能生成 RK3588 DRAM/Cache 干扰结论；中断源样本频率也不能直接充当独立的非关键中断压力 A。

### 2.2 下一执行门

真板基线、首组 A+B 及记录器 4 块配对已验收，原 QEMU A+B 超时仍未解释。下一步按当前执行核心补 IRQ 分发/计时器同步阶段，核实 GuestEntryBoundary 与 ERET 的区别及跨核阶段重叠，量化新增观测和残余握手成本，并取得当前频率/温度/固件证据。之后固定匹配配置运行重复四组；只对同口径运行级均值估计 I_AB，不用分位数非加性或记录器开关差值证明耦合。无稳健交互时保留否定结果，不推进预设 Joint 策略。

## 3. 数据口径

当前字段复跑确认数据能够生成，但字段名称不能替代物理语义。论文级指标必须由任务契约定义。

### 3.1 定时器到期

virtualization/axvm/tests/vcpu_runtime.rs 的 physical_deadlines 与 analyze_virq_physical.py 中的 due_ticks 指向触发物理中断的比较器时间。现有 deadline_miss 判断 Guest ISR 是否晚于此触发时刻。本次 64/64 为 true；这是触发之后的软件响应，不是实时任务截止期违约的证据。results/field-verification.json 保留这个观测并将 task_deadline_miss_ratio 明确置空。旧字段不改写，避免破坏已有数据契约。

### 3.2 任务完成

原 ISR 终点只覆盖 ISR 本身；第 6 节增加可关闭的单在途线程任务 T6，第 10 节进一步验证逻辑周期 release、排队和积压，并从计划释放计算任务预算分类。逻辑计划不等于外部定时硬件到达，设备输出尚未实现。事件响应、定时器到期延迟和线程任务完成分别报告，不用单次 QEMU 分类保证真实 Deadline。当前测试直接调用 AxVM；生产 AxVisor 的 irq_handler()/check_events() 路径仍须核对后插桩，不能把测试框架路径当作已覆盖生产 VMM。

## 4. 真板启动结果

已有 vcpu_perf 用例通过标准 cargo xtask ktest board 入口实际运行。测试使用内存型 ArceOS Guest，不调用机器人应用。

### 4.1 可运行证据

宿主与 Guest 均在 RK3588 启动，Guest 完成预热及五个测量窗口。原始日志为 raw/board-vcpu-perf-failed.log，精确命令与数值保存在 results/board-vcpu-perf.json。这确认基本板卡运行入口可用，仍未证明实时 Guest + Linux 双 VM 平台或中断时间链。

### 4.2 失败与下一门

套件未通过：吞吐 317532.16 blocks/s，低于已有门槛 328339.80（约 3.29%）。日志同时报告 A55 PVTM grade 2 无已验证高 OPP、保留启动 OPP，以及 A76 OPP 不可用、限制 816 MHz。该配置差异是待排查混杂，单次运行不能证明频率就是退化原因。没有下调测试门槛、强制未验证 OPP 或把失败改记为成功。下次先核实启动频率及基线可比性，再固定平台执行研究实验；本轮未修改驱动和调度实现。

## 5. 复放与完整性

本目录的 raw 保存真实输出，configs 固定输入身份，results 保存分析结果，SHA256SUMS 覆盖本次证据。归档脚本负责复放与校验；测量扩展只作用于测试路径，未改变生产调度策略。

### 5.1 离线复放

在仓库根目录执行 sh research/cross-path-20261017/replay-fields.sh 可重新运行 physical、runtime、ready 和 ISR 四类分析器；本轮已实际复放通过。sh -n 检查两个新增脚本通过，git diff --check 通过。

### 5.2 归档校验

在仓库根目录执行 sha256sum -c research/cross-path-20261017/SHA256SUMS 检查本目录证据完整性。真板测试退出码为 1 并保留失败记录，QEMU 字段测试退出码为 0。板卡测试结束后已查询服务，BallPick-Robot 显示 1/1 可用，当前没有本轮占用的板卡租约。

## 6. 线程任务完成验证

本次扩展仅用于阶段 1：通过真实 Guest 线程执行，建立 ISR 后的任务起止、已知答案校验和独立任务截止期。设计与同步证明见 [任务完成测量设计](design/task-completion.md)，实现位于 task_completion.rs、Guest execute_task() 和 analyze_virq_task.py。

### 6.1 真实运行与复放

三组运行全部由标准 cargo xtask ktest qemu 入口执行，均取得 AXTEST_SUITE_OK。原始日志、生成资源、二进制哈希、源代码归档及分析 CSV/JSON 分别保存在 raw/task-*.log、configs/task-*、configs/task-measurement-sources.tar.gz 和 results/task-*。

| 运行 | 每策略样本 | 任务记录 | 追踪记录 | dropped / incomplete |
| --- | --- | --- | --- | --- |
| task-on-32 | 32 | 64 | 3126 | 0 / 0 |
| task-on-260 | 260 | 520 | 5731 | 0 / 0 |
| task-off-32 | 32 | 0 | 3311 | 0 / 0 |

全部 584 条任务校验和正确且 ISR end ≤ task start ≤ task end。260 条运行经过计数低字节回绕，关闭模式保持原布局且不输出任务记录。results/task-contract-verification.json 保留逐组关联情况和 Deadline 分类。通过 sh research/cross-path-20261017/replay-tasks.sh 可从三组原始日志重新计算五类分析结果（关闭模式不生成任务指标）；本轮已实际执行通过。

### 6.2 测试与剩余门

23 项离线分析测试在远端通过。沿用原 ISR 测试发现并修复终点因果校验缺失：Host 已检查 ISR end，但离线分析器此前会接受晚于 Host 确认窗口的 ISR end；临时副本删除该检查后同一测试确定失败，红测日志保存在 raw/isr-causal-regression-red.txt。没有修改失败匹配或既有性能门槛。

任务 Deadline 配置为 Host submit 起算的 10 ms，与物理比较器触发时刻无关；时钟区间跨越 Deadline 时仍计 unknown。任务模式自旋等待，因此开关运行的差异不是纯探针成本；本轮不计算优化收益或交互项。M1 仍未通过：尚缺周期释放/积压、生产路径分解、同工作负载追踪开销、双 VM 真实 A/B 压力及真板测量。


### 6.3 静态检查与当前工作树

cargo fmt 已执行，cargo xtask clippy --package axvm 的 21 项检查全部通过，完整输出见 raw/task-clippy.txt。本轮源码补丁为 patches/task-completion.patch；它以本轮开始时的工作树为基线，不撤销用户已有修改，并已在临时副本验证 git apply --check 和应用后逐文件与冻结源码一致。configs/task-worktree.patch 另保留相对于 Git HEAD 的完整差异，包含原先已有修改；两者不可混淆。

上轮最终核查发现另一份新出现的 test_virq_interaction_analysis.py 引用尚不存在的 analyze_virq_interaction。此前 23 项分析测试均通过；新增文件出现后的全量发现运行结果为 23 项通过、1 项导入错误，见 raw/task-final-analysis-sweep.txt。当时保留该文件并记录缺口；第 7 节已补齐实现并重新验证全套通过，未修改原三项测试。该缺口不影响已经归档并复放通过的三组任务测量证据。

## 7. 双 VM 与阻塞任务

本轮补齐固定镜像恢复、Linux CPU 负载与任务测量的组合，并通过内核信号量验证真实 vCPU 等待/唤醒。它推进阶段 0～1，尚未完成论文的周期四组干扰实验。

### 7.1 交互分析与输入恢复

analyze_virq_interaction.py 已补齐，保留原三项测试，并验证完整实验块重采样和非法输入拒绝。summarize_replicates() 的每个输入元素必须是独立运行的均值，同下标对应 0/A/B/AB 同一实验块；不接受把单次运行事件当作重复，也不用于分位数交互。当前未采集四组数据，尚无实测交互结论。

Linux 内核恢复为原固定 SHA；新 BusyBox 基底使用单独的 registry-v0.0.14 配置和固定 SHA，legacy 默认校验保留。VIRQ_LINUX_CC 与 Zephyr 裸机工具链分离，build.json 记录实际编译与镜像身份。legacy 配置拒绝新基底且不产生输出，负测证据见 results/legacy-input-check.json。完整命令见 Linux Guest README，设计见 design/dual-vm-inputs-and-interaction.md。

### 7.2 调度链与观测边界

VIRQ_TASK_WAIT=blocked 使用 Zephyr 信号量及 idle WFI。源码确认 AxVM 将 WFI 转为 VcpuAction::Wait；ISR 先发布计数再 give，线程 take 后执行任务，避免应用层检查/入睡竞态。各组原始日志、资源与源码身份均按运行名称独立归档，汇总见 results/phase01-functional-audit.json。

| 运行 | 每策略样本 | 完整调度链 Fair/FIFO | 追踪记录 | dropped / incomplete |
| --- | --- | --- | --- | --- |
| dual-linux-task-32，自旋 | 32 | 0 / 0 | 10532 | 0 / 0 |
| task-blocked-32，阻塞 | 32 | 32 / 32 | 3891 | 0 / 0 |
| dual-linux-blocked-32，双 VM 阻塞 | 32 | 28 / 32 | 11629 | 0 / 0 |
| task-disabled-8，原模式回归 | 8 | 8 / 8 | 2829 | 0 / 0 |

三个开启任务的组均有 64 条有效 ISR→T6 记录。自旋组所有目标都已运行，无新唤醒切换；双 VM 阻塞组有 4 条 Fair 样本同样为 running_no_new_switch，原样保留在分母和状态分类中，没有拼造 Ready 时间点。其余 60 条关联到 Ready/Running。所有任务均通过 checksum、时间顺序与独立 10 ms 预算分类，不能外推为真实应用 Deadline 保证。

首次阻塞试跑因原非目标核静止断言失败，源码与日志分别保存在 configs/task-blocked-initial-failed-sources.tar.gz 和 raw/task-blocked-initial-failed.log。新模式明确报告后台 Guest 核恢复次数：单 VM Fair/FIFO 为 31/32，双 VM 为 34/32；具体来源尚未归因，不宣称零后台活动。spin/关闭模式保留原静止断言，关闭回归两策略均为零。关键 vector48 的目标 CPU、逐条计数、源处理次数和任务结果检查持续保留。

### 7.3 验证与继续条件

当前 28 项分析测试与 cargo xtask clippy --package axvm 的 21 项检查通过，cargo fmt --package axvm 已执行；日志见 raw/task-blocked-analysis-tests.txt 和 raw/task-blocked-clippy.txt。补丁 patches/dual-linux-inputs-and-interaction.patch、patches/task-blocking.patch 与设计文档分别说明新增输入和等待模式；阻塞补丁已在隔离基线验证应用后源码一致。

sh research/cross-path-20261017/replay-phase01.sh 可复放本节四组，原 replay-tasks.sh 继续复放旧三组。新双 VM 阻塞组保存了 Host initramfs 整体哈希；此前自旋双 VM 组未捕获整包哈希，已在其 provenance.json 明示，仅保留当时的分件身份与配置。追踪导出耗时发生在采样完成后，不能当作任务时延。

M1/M2 仍未通过：下一步建立周期释放与积压协议，在相同工作负载上量化追踪开销，接入独立非关键 IRQ 压力 A 与 Linux 内存压力 B，再做真板频率/温度/计数器核查和重复随机化四组实验。当前 Linux 仅为 CPU 负载，进度为粗粒度工作量，尚不满足 DRAM 流量或精确普通 VM 吞吐指标；未新增联合优化控制器。

## 8. Linux 内存压力

本轮在原 CPU 对照上接入 linux_memory，推进阶段 2 压力源 B 的功能实现。第 7 节“仅 CPU”的描述属于此前检查点；本节取代该项状态，不改变此前归档结果。设计见 [内存压力设计](design/linux-memory-pressure.md)，源码由 linux-load/workload.c、prepare.py、support/linux.rs 和 analyze_virq_load.py 共同定义。

### 8.1 独立校验

两种模式沿用相同 Linux vCPU、Host CPU3 和每批 8192 次 LCG；内存模式额外对私有数组顺序读改写，每次读取都检查 index+已完成轮数。memory_settings() 为编译参数和 Host 资源提供同一配置来源，默认 16 MiB、每批访问，支持 1～64 MiB 和每 1～1024 批访问一次。完整进度行同时携带 CPU 与内存计数；MemoryConfig::expected() 与离线闭式求和独立核对批数、逻辑字节和写值校验和。

verify-linux-memory-worker.py 已在原生 Linux 实际编译运行 CPU 对照、16 MiB 默认模式和 1056768 字节/每三批模式，后两者均经过多圈访问，后者还覆盖部分圈。临时副本故意破坏数组初值后以退出码 1 拒绝，并无成功进度记录。原始输出与编译身份见 raw/linux-memory-native/，该验证不能替代虚拟机证据。

既有负载测试扩展后在旧分析器上确定失败，包含此前 CPU 日志夹带 MEMORY_READY 却未被拒绝的缺口，证据见 raw/linux-memory-analysis-red.txt。现 28 项分析测试、axvm 的 21 项 Clippy 检查通过，旧七组真实日志复放通过；分别见 raw/linux-memory-analysis-tests.txt、raw/linux-memory-clippy.txt 和 raw/linux-memory-legacy-replay.txt。增量补丁 patches/linux-memory-pressure.patch 已在保存的原工作树副本验证应用后逐文件一致，详见 results/linux-memory-patch-verification.json。

### 8.2 双 VM 验收

dual-linux-memory-blocked-128 使用阻塞实时任务、16 MiB 内存数组和原 PL031 SPI，每策略 128 条记录；标准 xtask 返回成功，七类分析全部通过。共 256 条有效任务和 16413 条追踪记录，dropped/incomplete 均为 0。Fair 有 120 条完整唤醒关联、8 条 running_no_new_switch；FIFO 有 128 条完整关联，全部任务校验和与 10 ms 预算分类有效，未将缺少新切换的事件排除。

两策略各自采样窗口均观测到逻辑读取 32 MiB、写入 32 MiB；Fair 126/128、FIFO 127/128 的逐事件窗口没有新的完整串口进度，原样保留为零观察进度。该粗粒度记录不能说明这些窗口没有真实访问，也不能推出逐 ISR 吞吐。后台 Guest 核返回次数为 131/128，仍不声称后台静止。

每组 configs 保存资源、Guest 配置、编译信息、源码和实际 Host kernel/initrd 的摘要。configs/linux-memory-sources.tar.gz 固定本轮源码，capture-linux-memory.py 在后续构建覆盖前校验源码身份并保存产物哈希。run-linux-memory.sh 为运行入口；在归档目录执行 sh replay-linux-memory.sh dual-linux-memory-blocked-128 dual-linux-cpu-blocked-128 可从两组完整原始日志复放七类分析。QEMU 追踪导出耗时发生在采样后，不能作为任务时延。

### 8.3 后续验收门

相同样本数与拓扑的 dual-linux-cpu-blocked-128 已完成，xtask 与七类分析均通过，256 条有效任务和 15710 条追踪记录无丢失/残缺。Fair 有 126 条完整关联、2 条 running_no_new_switch，FIFO 有 128 条完整关联；所有任务的 10 ms 预算分类均为 false。audit-linux-memory.py 已核对两组源码、锁文件、实时 Guest 配置与 Linux 拓扑相同；results/linux-memory-functional-audit.json 明示 M1/M2 仍未通过。CPU 对照不分配数组并保留旧进度格式，是 B0；增加内存访问的是 B1，不能以此前单 VM 代替 B0。

尚缺周期释放与积压、生产 IRQ/timer 分解、相同工作负载追踪开销、独立非关键 IRQ 压力 A、真板频率/温度/计数器与内存压力验证，以及重复随机化四组实验。逻辑内存操作不等于 DRAM 事务，额外校验也有计算成本；QEMU 单次功能组不能估计真实耦合或优化收益。本轮没有计算实测交互项，没有新增联合控制器。

## 9. 独立中断压力

本轮为第 8 节尚缺的 A 增加独立 SGI15 合成压力，关键事件继续使用 PL031 SPI34，Host 调度器继续使用原时钟。问题、替代方案、GIC 路径与同步证明见 [独立 IRQ 压力设计](design/irq-pressure.md)。这仅推进阶段 0～2 的源装配，未进入机制归因或协同控制。

### 9.1 所有权与控制

support/irq_pressure.rs 的 Pressure 守卫独占 request_irq() 句柄和 CPU2 发送线程，目标为 CPU0。系统 IPI 是 SGI0，申请冲突会失败，不覆盖 handler；Guest 仍在 CPU0/1、Linux 仍在 CPU3。SGI15 进入常规 IRQ framework 分发，并在 handler 验证 INTID、CPU 和 hard IRQ 上下文。它是合成物理 GIC IRQ，不是 Linux 设备、网络或 DMA 压力的证据。

每个周期发送 1～8 个串行确认的请求，周期可设为 100～1000000 us；handler 做以序号为 seed 的固定 64 步已知答案工作。下一次发送必须先 Acquire 观察到前次 handler 完成，避免用发送次数推定交付次数。实际计划/发送/handler 起止/完成观察时间均使用 Host counter，超期跳过而不补发积压。每策略最多 4096 次；耗尽、超时或身份错误均拒绝验收，不静默降压。

停止顺序为 stop→join→disable→synchronize→free；Arc 保持 handler 状态存活，未新增 unsafe。测量窗口的时间与完成计数在 CPU0 的短 IRQ exclusion 下共同取样，防止跨越窗口边界的回调被错计入。回调 end 时间在回复发布前，不覆盖 pre-IAR 或之后的 EOI/调度尾部。未申请新的生产追踪 observer，也未修改关键 IRQ 计数断言。

### 9.2 真实装配与关闭

两组都使用阻塞实时任务、16 MiB Linux 内存负载、每策略 128 条记录；唯一测例资源差异为 irq_pressure=sgi/off。完整日志、测例资源、Guest/Host 产物摘要分别位于 raw/dual-linux-memory-sgi*.log 和 configs/dual-linux-memory-sgi*/。两组均由标准 xtask 返回 AXTEST_SUITE_OK，并通过最终八类离线分析。

| 运行 | SGI Fair/FIFO | 完整唤醒关联 Fair/FIFO | 追踪记录 | dropped / incomplete |
| --- | --- | --- | --- | --- |
| dual-linux-memory-sgi-128 | 324 / 384 | 126 / 127 | 16975 | 0 / 0 |
| dual-linux-memory-sgi-off-128 | 0 / 0 | 126 / 128 | 15734 | 0 / 0 |

开启组的测量窗口内实际确认 322/382 次回调，对应约 996.59/999.14 Hz；包含预热的完整发送数与处理数逐条相等，错误为零，两策略都完成 join 与 IRQ 回收。Fair 有 127/128、FIFO 有 128/128 个 submit→任务观察区间与回调 body 正时长相交。零相交窗口仍在分母，相交仅表明同时发生，不能证明因果；未相交也不能排除排队或其他干扰。

四个策略运行均有 128 条有效任务，10 ms 预算分类均为 false，不能外推为真实 Deadline 保证。缺少新切换的记录全部保留；后台 Guest 核返回开启组为 133/128、关闭组为 134/128，没有声称静止或归因于某一种 IRQ。完整事实与拓扑/源码匹配检查见 results/irq-pressure-functional-audit.json。

### 9.3 复放与证据版本

sh research/cross-path-20261017/replay-irq-pressure.sh 可从两组完整日志复算八类结果。30 项分析测试、axvm 21 项 Clippy 检查通过；此前九组实际日志也已复放通过。旧分析器忽略错误压力配置的红测在 raw/irq-pressure-analysis-red.txt；后续增强还发现压力频率与关键链频率不一致时未拒绝，确定性红测在 raw/irq-pressure-clock-red.txt。当前 verify_window() 集中验证相同 counter frequency 和完整 ISR/任务观察窗口。

两组运行的编译输入相同，原始源码冻结为 configs/irq-pressure-sources.tar.gz。上述最终时钟校验在两组运行均捕获身份之后更新，未改动已测 Host/Guest；最终分析器另冻为 configs/irq-pressure-final-analysis.tar.gz，并已重放两组。audit-irq-pressure.py 保存当前分析源码摘要，另验证现有非分析源码与运行时捕获一致，避免把不同版本混成一个来源。

run-irq-pressure.sh 接受运行名称、linux_cpu/linux_memory 和 sgi/off；使用新运行名称，脚本会先冻结本组源码再构建，不覆盖原始日志。此前两组使用公共冻结包，未来运行使用 configs/<name>/sources.tar.gz。patches/irq-pressure.patch 相对 configs/irq-pressure-before.tar 生成，已在隔离副本验证应用并逐文件一致；工作树原型未合入或发布。

本轮工具版本记录在 configs/irq-pressure-tool-versions-after-runs.txt，明确为两组完成后采集，不伪称运行前快照。未来运行脚本会在构建前记录工具版本，并在源码冻结失败时立即停止；当前实际编译和 QEMU 启动参数仍以完整原始日志及产物摘要为准。

### 9.4 剩余阶段门

合成 A 与 B 已在 QEMU 同时工作并可关闭，但尚无生产设备 IRQ 或真板内存干扰证据。CPU2 的发生器开销属于 A；串口进度、64 步 handler 工作及追踪成本都必须进入后续解释，不能仅凭两个开关可用就声称耦合。

M1/M2 仍未通过。下一步必须完成周期释放与积压、生产路径分解、相同工作负载探针开销和精确普通 VM 吞吐，随后核查真板 IRQ/频率/温控/计数器并运行重复随机化四组。当前未计算实测 I_AB，也未以开关单次结果推导优化收益。

## 10. 周期计划与积压

本轮扩展原先完成 T6 才请求下一项的协议，增加固定逻辑到达计划和 Guest 队列测量。设计见 [周期释放设计](design/periodic-release.md)。该阶段解决 Host 夹具不能观察任务跨周期积压的问题，仍不是外部设备精确定时产生中断的证据。

### 10.1 释放与发布

support/periodic.rs::Schedule 生成固定计划 t_i=epoch+(i-1)P。Host 不再等待上一任务完成，只等待 ISR 确认；仍保留一个未确认关键 IRQ，避免 GIC pending 位合并并保持逐项物理 IRQ/Guest ISR/任务关联。迟到时不跳过任务，PERIODIC_RELEASE 同时记录计划、实际 submit 和当时已到期但尚未提交的 Host 队列。计划到达与实际硬件触发不可混称。

Guest 的计数信号量上限为 N，总共恰有 N 次 give；isr_outstanding 表示包括新任务的未完成数，task_outstanding 表示任务开始时包括自己的未完成数。周期模式在任务开始/received 快照及 T6/completed 发布处各使用短 IRQ exclusion，避免时间戳与计数之间插入 ISR 造成虚假积压。Host 以独立的 ISR/T6 时间序列重算这些数，counter tick 相同的先后保留可能范围。

完成后 Guest 发布 TASKS_DRAINED 完整行；Config::drain() 再确认稳定的 full count=N 并读取全部不可变槽，不用低字节猜测所有任务已经完成。原 task protocol=1 前缀保留，周期扩展独立版本为 1、mailbox 总大小为 64+56N；period=0 时仍为 56+40N。ELF symbol size、Guest static assertion 和 Host RAM 边界共同验证布局。

### 10.2 工作量与截止期

VIRQ_PERIOD_US=0 默认保留旧模式；100～1000000 us 开启计划释放。周期任务支持 VIRQ_TASK_ROUNDS=4096～1048576，Host/Python 独立验证配置对应的 LCG 结果；旧模式必须保持 4096 轮。所有任务仍串行执行，不把队列积压误作多线程执行重叠。

周期 Deadline 从计划释放起算，包含 Host 迟到和 Guest 排队；旧模式从实际 Host submit 起算。原 submit→T6 指标保留，新增 release→T6、释放迟到、Host 到期积压、Guest outstanding。每项 Host observed 是同一批量确认时刻，真实 T6 仍由 Guest 时间戳经校准求区间，不把批量确认时间伪装为每项完成时间。

确定性测试验证：同一项任务按 submit 起算会在预算内，按计划释放却超期；临时删除新起算逻辑的副本必然失败，见 raw/periodic-deadline-origin-red.txt。还增强了 A 活跃窗口校验，要求覆盖完整计划释放→任务观察，错误地从 submit 才开始的压力会被拒绝，红测见 raw/periodic-pressure-origin-red.txt。32 项分析测试与 axvm 21 项 Clippy 检查通过，均未放宽计数、Linux 进度或成功匹配。

### 10.3 实际运行

以下四个成功配置均使用同一四核双 VM 拓扑及 Linux 16 MiB 内存负载。工作量和计划周期不同仅用于功能验证，不是可用于耦合或优化收益估计的四组因子实验。全部 448 条任务记录有效，所有追踪 dropped/incomplete 均为 0。

| 配置 | 每策略任务 | 周期/轮数 | Guest 未完成峰值 Fair/FIFO | 追踪记录 |
| --- | --- | --- | --- | --- |
| periodic-backlog-32 | 32 | 250 us / 1048576 | 26 / 28 | 12249 |
| periodic-normal-32 | 32 | 20000 us / 4096 | 1 / 1 | 14474 |
| periodic-disabled-128 | 128 | 关闭 / 4096 | 旧协议不采集 | 15752 |
| periodic-ab-backlog-32 | 32 | 250 us / 1048576，A 开启 | 26 / 27 | 13796 |

未开启 A 的过载配置两策略各有 31/32 项到达时仍有先前任务未完成，Host 到期未提交峰值为 30/29；A+B 配置对应值为 31/32、Host 峰值 30/29。三组周期数据均由时间戳独立验证积压，所有 N 项均排空。过载两组的 10 ms 计划释放预算全部超期，低工作量组和关闭组全部为 false；这只是当前构造工作量下的分类，不能外推 Deadline 保证或因果收益。

过载和 A+B 两组每策略均仅 1 项出现新的完整唤醒切换，其余 31 项为 running_no_new_switch；任务正持续运行时不应伪造新 Ready/Running。低工作量组 32/32、关闭组 128/128 均完整关联，所有记录保留在分母。A+B 组确认 SGI 发送/处理 292/258 次、错误为零，完成 join 与 IRQ 回收，并验证压力在计划释放前已活跃。

periodic-disabled-32 是一次明确失败的尝试：关键 RTC 已处理并回收 32 次，但采样窗口未观察到新的完整 Linux 进度报告，原断言拒绝了该组。日志、源码和 exit=1 身份均保存，未将其作为有效样本；随后用 128 项扩大同一旧模式观察窗口，保持原验收条件后通过。粗粒度报告未变化不代表 Linux 没有执行。

### 10.4 复现与剩余门

run-periodic.sh 接受新名称、period_us、rounds、sgi/off、linux_cpu/linux_memory、样本数，内部使用标准 xtask 并在每组构建前冻结 sources.tar.gz 和工具版本。周期模式默认 32 项，关闭模式根据上述观察不足改为默认 128 项；显式样本参数和原始失败均保留，不放宽验收。每组 provenance 保留 Guest/Host 实际产物摘要；audit-periodic.py 验证四组非分析源码相同、当前编译源码与捕获一致、Git/依赖身份相同，并将失败尝试单独列为 accepted=false。完整验收见 results/periodic-functional-audit.json。

sh research/cross-path-20261017/replay-periodic.sh 可复算四组全部结果，周期组执行九类分析，关闭组执行八类；此前十一组真实日志也已用最终分析器复放。最终派生结果以 configs/periodic-final-analysis.tar.gz 与 audit 中的分析源码摘要为准，运行身份中的源码包保持原测量版本。完整日志导出发生在采样之后，导出墙钟耗时不是任务响应时间。

patches/periodic-release.patch 相对于 configs/periodic-before.tar 保存增量，并在隔离副本验证应用后逐文件一致。修改限于测例、Guest、准备和分析，未新增 unsafe、未修改生产 IRQ/定时器语义、未合入或发布。周期 Host 计划及 Guest 积压的功能闭环已建立；外部定时硬件到达、生产路径分解、相同工作负载追踪开销、精确普通 VM 吞吐和真板验证仍未完成，M1/M2 保持 false，也未计算实测 I_AB。

## 11. Linux 吞吐边界

本轮补充普通 VM 的时间分母与采样边界，设计先于实现归档为 [Linux 有边界吞吐](design/linux-fenced-throughput.md)。CPU 与短内存组的握手已完成原生及 QEMU 验证；新的 A+B 积压组合发生关键交付等待超时，仍须定位，不能把局部成功称为完整干扰实验闭环。

### 11.1 因果快照

`VIRQ_LINUX_FENCES=0` 保留旧 READY1 与严格完整报告进度；1 使用 READY2 和独立 FENCE1。`ConsoleBuffer` 的固定容量输入队列由每个 UART generation 独立拥有，`Fixture::send_input()` 在释放 IRQ-safe 队列锁后调用现有 `VmHandle::notify_devices()`。设备读取不分配、不阻塞，不新增生产接口或 unsafe。

Linux `workload.c` 的 SIGIO handler 只置标志；主线程在完成 8192 步工作后读取 B/E，取得同一批次的 LCG、内存计数及 `CLOCK_MONOTONIC_RAW` 快照。重复、倒序、未知请求与错误 CPU 均失败。`Progress::begin_window()` 完成后才创建周期计划，任务全部观察完成后才 `end_window()`，A 的启停顺序包住两次握手。工作循环不增加每批串口系统调用，但标志检查、SIGIO、回复及日志成本仍存在。

`Fences::finish()` 与 `analyze_virq_linux_fence.py` 独立校验 CRC、相邻报告顺序、配置、阶段、正工作量与正 elapsed；Guest elapsed 必须处于 Host request/observed 因果界内，容差只含时钟量化和声明分辨率。`verify_fence_window()` 在任务分析中使用周期计划释放，确保 Begin-observed→End-request 包住计划释放→任务观察；A 活跃窗口还必须覆盖 Begin-request→End-observed。因果界不是统计置信区间。

### 11.2 已验收数据

两个启用成功配置各有两种策略、每策略 32 项，共 128 条有效任务，10 ms 预算分类全部为 false，追踪 dropped/incomplete 均为 0。它们用于验证协议与不同任务模式，参数不构成四组因子对照，也不能据其差异推导性能收益。

| 配置 | 周期/轮数 | 快照间完成批次 Fair/FIFO | Guest elapsed ms Fair/FIFO | 追踪记录 |
| --- | --- | --- | --- | --- |
| throughput-periodic-cpu-32 | 20000 us / 4096 | 2319 / 2560 | 774.858 / 824.749 | 15918 |
| throughput-memory-short-32 | 关闭 / 4096 | 181 / 256 | 273.416 / 283.585 | 14076 |

内存组每次访问 16 MiB 工作集，快照区间内两策略分别完成逻辑读取 11862016/16777216 字节，写入相同字节数；不是 DRAM 流量。CPU 组两策略的 End 都为 5121 批，最后完整报告仅 5120；快照独立校验了这一批，End 之后到停止的工作仍不计入。粗粒度 start==end 的正工作量分支由通用协议测试覆盖，本轮启用成功组的完整报告均有增加。

启用组单次 Host 握手观察约 96～199 ms，包含当前 QEMU、串口输出和控制服务成本，不是纯 IRQ 或 SIGIO handler 开销。吞吐只代表明确快照区间内的工作量/墙钟时间，区间含控制成本；逐 ISR 吞吐和等工作量探针开销仍未得到验证。关闭组 `throughput-off-128` 使用每策略 128 项与原始完整报告进度验收，不产生快照速率。

关闭组 xtask 与八类分析均通过，新增 256 条有效任务、15709 条追踪，dropped/incomplete 均为 0，10 ms 预算分类均为 false。Fair 的 126 项完整关联及 2 项 `running_no_new_switch` 全部保留，FIFO 的 128 项完整关联；完整报告计数分别从 1280→1536、1024→1792，未放宽原进度条件。本轮三个成功组合计 384 条任务，A+B 失败尝试不计入。

### 11.3 拒绝与诊断

`throughput-ab-backlog-32` 使用 250 us、1048576 轮、SGI15 和 16 MiB 内存压力。Fair 返回 Begin=1519 批，随后以 `mailbox timed out: [1, 1, 3, 3, 0]` 失败，清理还报告压力容量耗尽；原始日志、exit=1、源码与实际产物身份均保存，`accepted=false`。未放宽关键 IRQ、超时、容量或成功规则，也未把失败部分计入有效任务样本。

现有错误没有记录当时预期样本号，也没有保存 Host RTC handled/errors 与设备状态，故 received=3 不能区分等待下一项与遗漏 exact-count 确认。成功组还改变了周期/工作量等参数，不能用它们归因为 SGI 或握手。具体证据缺口与配对诊断计划见 `results/throughput-failure-triage.json`；下一步先增加失败现场的预期样本号和只读计数，再保持其他参数固定分别关闭 A 或握手。QEMU 8.2.2 的上游 PL031 模型仅作为寄存器语义参考，不作为根因证明。

旧负载分析器会忽略无声明的非法快照，确定性红测保存在 `raw/throughput-analysis-red.txt`。实际任务 CLI 的另一次变异把 Begin-observed 放到首个计划释放之后、实际 submit 之前；当前实现 exit=1，临时改成从 submit 校验的副本 exit=0，见 `results/throughput-fence-window-rejection.json`。该变异日志明确为合成坏数据，不是测量样本。

### 11.4 交付边界

真实 Linux PTY/SIGIO 使用同一 C worker，CPU/内存开启与关闭、重复 Begin、先发 End 共六个场景通过，任意批次 CRC 和父进程 raw-clock 时间包含关系均验证，进程均已回收。`results/throughput-native-v1/` 保存日志与编译/源码/产物摘要；原生测试不替代虚拟 UART 和 VM 服务验证。35 项分析测试、axvm 21 项 Clippy 检查通过；此前四组周期日志已由新分析器完整重放。

第 10 节四组日志的当前派生结果由本轮分析器再次重算，版本来源为 `configs/throughput-final-analysis.tar.gz` 与 `results/throughput-functional-audit.json` 中的摘要。原始运行捕获、旧的 `periodic-final-analysis.tar.gz` 和历史审计仍保存原版本身份，不把新派生结果伪称为旧分析器输出。

`run-throughput.sh` 接受新名称、period_us、rounds、sgi/off、linux_cpu/linux_memory、样本数、握手开关，内部复用标准 xtask 的 `run-periodic.sh`，并在每组构建前冻结全部测例源码和工具版本。`replay-throughput.sh` 默认仅重放成功组，启用组额外运行吞吐分析；`audit-throughput.py` 同时核对成功与失败的源码包、Git/锁文件、原生产物来源及当前源码，保留失败原因。当前不发布、不合入。

`patches/linux-fenced-throughput.patch` 相对 `configs/throughput-before.tar` 包含 14 个文件增量，`package-throughput.py` 已在隔离副本实际应用并逐文件匹配。M1/M2 继续为 false：尚缺 A+B 超时定位、外部定时到达与生产路径分解、等工作量探针/握手成本、真板频率/温控/计数器及重复随机化四组与交互不确定性。本轮没有计算实测 I_AB，也没有新增联合控制器。

## 12. 交付配对诊断

本轮针对第 11 节失败的证据缺口增加现场观测，并固定其他参数分别关闭握手或 SGI。设计先于实现归档为 [交付失败现场](design/delivery-failure-diagnostics.md)。三组均通过，但没有重现原故障，也没有获得自然失败时的诊断分支运行证据；根因和修复仍未证明。

### 12.1 失败观测

`vcpu_runtime.rs` 在关键 acknowledgement 等待返回错误后打印 `VIRQ_DELIVERY_FAILURE`，包含预期样本号、提交/失败 Host counter、Guest header/任务发布及 VM 状态，随后保留原错误与非零退出。`RtcSpi::report_failure()` 读取 DR/MR/IMSC/RIS/MIS 和既有计数，输出前释放 bank 锁及局部 IRQ exclusion。`Pressure::report_failure()` 顺序读取已有原子状态，不把跨 CPU 字段称为同一原子快照。

`Counters` 将原错误短路分支细分为 wrong_cpu、invalid_alarm、pulse_failed，只在原错误发生时增加分类计数，成功 handler 不增加原子写或日志。原有总 errors=0、IRQ 计数、超时、压力容量、任务排空与所有回收顺序均保持。框架 `irq_status()` 的平台后端对硬件 enabled/pending/active 返回 Unsupported；报告只取框架状态，hardware_pending/active 明确为 unknown，不用其 false 回退值推断硬件无挂起。

### 12.2 固定参数控制

三组使用同一测例源码、Git/锁文件、32 项/策略、250 us 逻辑周期、1048576 轮、16 MiB/every=1、CPU0 服务和原有拓扑，仅改变 irq_pressure 或 linux_fences_enabled。所有 192 条任务有效、追踪 dropped/incomplete 均为 0；这是诊断功能控制，不是硬件因子实验或吞吐收益比较。

| 配置 | SGI | 握手 | SGI handled Fair/FIFO | 追踪记录 |
| --- | --- | --- | --- | --- |
| delivery-ab-fenced-32 | 开启 | 开启 | 634 / 610 | 16158 |
| delivery-ab-unfenced-32 | 开启 | 关闭 | 252 / 236 | 12441 |
| delivery-memory-fenced-32 | 关闭 | 开启 | 0 / 0 | 14149 |

每组两种策略均完成 RTC 32 次、errors=0、IRQ 回收与任务排空。全部任务的 10 ms 计划释放预算分类为 true；Guest 未完成峰值分别为 26/25、26/26、26/26，属于构造的重负载积压，不能据此归因为 A 或握手。开启 A 的吞吐快照包围任务计划且完整握手受压力覆盖；关闭组仍要求完整报告进度，不增加快照速率。不同 A 事件数包含控制窗口长度变化，不作为同强度硬件比较。

### 12.3 来源与复放

`run-delivery-control.sh` 接受新名称及 ab_fenced/ab_unfenced/memory_fenced，固定上述公共参数，内部使用标准 xtask。每组独立保存源码包、环境、资源、工具版本、退出码与实际产物摘要；三组分别通过原有逐事件分析，启用组额外通过吞吐分析。`audit-delivery.py` 核对源码包与当前测例一致、资源仅差两个开关、结果完整，并明确 `natural_failure_snapshot_observed=false`。生产源码与 HEAD 的一致性在事后核对，不冒称构建前检查。

在仓库根目录执行 `sh research/cross-path-20261017/replay-throughput.sh delivery-ab-fenced-32 delivery-ab-unfenced-32 delivery-memory-fenced-32` 可复算三组。诊断补丁 `patches/delivery-diagnostics.patch` 相对 `configs/delivery-diagnostics-before.tar` 仅改三个测例文件，已由 `package-increment.py` 在隔离副本实际应用并逐文件匹配；21 项 axvm Clippy 检查通过，未新增 unsafe、未改生产代码、未合入或发布。

历史 audit 中的 live-source 一致性是当时检查点的结论；当前新增诊断会使要求旧源码的审计拒绝最新工作树，不能冒称旧二进制由新源码编译。历史完整日志可由未改动的分析器复放；恢复旧源码应使用对应 configs 中的冻结包，原始运行身份不重写。

### 12.4 剩余阶段门

原 `throughput-ab-backlog-32` 仍为 accepted=false。新诊断改变了测试二进制，三个有限成功控制不能证明原失败由某一开关或诊断改动引起，更不能称为修复。失败分支尚缺实际运行验证；后续需有明确故障模型的验证或新的自然现场，不通过无限重跑维持绿色。

`results/rk3588-timechain-entry-audit.json` 固定下一真板入口：AArch64 虚拟机器模型与 Host UART 独立，可复用虚拟 PL011/GICv3；当前阻挡来自 RTC/CNTP/SGI 与 Linux/周期组合的显式 QEMU 准入。需先核实 RK3588 的 EL、Host timer PPI 和 Guest CNTP trap，再按真实资源与独占所有权设计板卡配置，不能直接删除守卫。原板卡吞吐失败及频率混杂仍保留。本轮未取得新板卡租约，M1/M2、真实耦合及联合控制门均保持未通过。

## 13. 真板双 VM 入口与复位失败

本轮设计归档为 [原生时间链入口](design/native-timechain.md)。QEMU 的显式固件/CNTP 双 VM 组合通过；真实 RK3588 的 Linux 和双核 Zephyr 首次启动成功，但复位后的 Zephyr 未再次 Ready，套件失败，没有有效真板采样。完整性审计见 `results/native-timechain-audit.json`，失败现场及下一证据需求见 `results/native-board-reset-triage.json`。

### 13.1 资源与固件契约

第 12 节仅根据架构后备模型推断 Guest UART 独立并不充分：`resolve_console_source()` 在没有显式 Guest DTB 时仍可能继承 Host UART。原判断原样存于 `configs/rk3588-entry-audit-before-explicit-dtb.json`，入口审计补充此修正。现在两个 Guest 都显式提供 DTB，Zephyr 使用同次编译产物，Linux 使用最小虚拟 PL011/GICv3/PSCI/架构 timer 描述；Guest CPU IDs 与 Host masks 分别配置。

保留生产 console/GIC 几何校验，`VIRQ_GIC_LAYOUT=qemu|rk3588` 分别匹配机器基线，仍由每 VM GIC 仿真。`VIRQ_EXPLICIT_DTB=1` 同时启用 Zephyr 原有运行时 timer frequency 读取，Ready 前核对 kernel rate 与 CNTFRQ。新增平台准入核对真实 FDT 身份、EL2、GICv3、标准 ARM timer PPIs 与 Host CNTHP26；原 CNTP30 独占、bank 保存恢复、CPU 固定及同步回收均保留。真板仅允许 CPU0 的 current-EL fixture，未扩大为 Guest-running 路径。

### 13.2 QEMU 功能验收

前三次尝试全部失败并保留：`native-ppi-qemu-cpu-32` 缺少显式 Zephyr DTB；v2 将解析器已归一化的根名 `/` 错认成非法；v3 的 Linux redistributor 窗口长度与 QEMU 基线不匹配。分别补充 DTB 生成、修正根名判断和选择匹配 GIC 几何，未删除生产校验或放宽成功规则。

`native-ppi-qemu-cpu-32-v4` 使用 32 项/策略、20 ms 逻辑周期、4096 轮、10 ms 任务预算、Linux CPU 工作量、A 关闭、吞吐握手开启。标准 xtask exit=0，Fair/FIFO 各 32 次 CNTP IRQ、errors=0、retired=1；64 条任务全部有效，预算分类均为 false，16984 条追踪 dropped/incomplete 均为 0。两策略时钟 offset 区间宽 1744/1792 ns，Linux 快照完成批次 2816/2842。九类原有分析及独立吞吐分析全部通过；这仍是 QEMU 功能证据。

### 13.3 RK3588 实际失败

通过标准 `cargo xtask ktest board` 在可用 `BallPick-Robot` 实际取得租约并 TFTP 启动，本轮为纯 Host initramfs 内存根，无持久存储刷写。构建解析出的特性没有 `rk3588-cpufreq`；这不证明 CPU 频率固定。日志、实际 Host DTB/FIT、两个 Guest 输入 DTB、工具/配置/源码与产物哈希均保存于本组 configs。Zephyr overlay 保留原节点名，dtc 报告 GIC unit-address 与新 reg 不一致的警告；实际 reg 及生产几何校验通过，不能据此警告确定复位根因。

宿主报告 `orangepi5plus_rk3588`、EL2、4 CPU、counter=24 MHz；Linux 在 Host CPU3 到达 READY2/FENCE1 并持续报告进度。Zephyr 两核首次 Ready，Guest MPIDR1，kernel timer 与 CNTFRQ 均为 24 MHz。随后原测例复位返回新 run，旧 memory/IRQ ports 拒绝访问；第二次等待 Ready 超时。发布快照是 Running、vCPU0 Ready、vCPU1 Free；`control/observations.rs` 对 started participant 发布 Ready，不能据此认定 vCPU 从未调度或仍在执行。

失败发生在第二次 Ready 之后的校准和物理源创建之前，未输出有效任务、物理 IRQ summary 或采样阶段标记，不能宣称真板 CNTP 投递已验证。原超时和套件失败规则保持，清理确认 VM group empty，runner 退出后板卡恢复可用。串口含非 UTF-8 原始字节，首次捕获脚本报错；补充只对解析使用 replacement 的处理后重建 exit=1、accepted=false 的来源记录，原始字节及 SHA-256 保留。

### 13.4 补丁、复放与下一门

`patches/native-timechain.patch` 相对 `configs/board-timechain-before.tar` 含 14 文件增量，包括测试、Guest 固件/准备器和平台技能参考；隔离副本实际应用后逐文件一致。axvm 21 项 Clippy 检查全部通过。本轮没有修改编译的生产源文件、合入或发布；`package-increment.py` 同时保留 baseline 中的技能文件，避免将未参与差异收集的文件误作删除。

`run-native-timechain.sh` 以新组名和 qemu/board 选择标准入口，构建前冻结测例；QEMU 成功组可用 `replay-throughput.sh native-ppi-qemu-cpu-32-v4` 复算，失败组不送入有效样本分析。审计脚本把成功与拒绝组分开，并核对冻结源码及日志身份。旧分析器仍保留 QEMU 范围文字，实际运行环境由本轮 provenance、平台标记和冻结固件确定，不能据旧文字把硬件结果当作模拟器结果或反过来。

下一步先为复位失败增加 run/entry/park 计数与生命周期边界，并在既有 VM 回收后冻结有损状态明确的诊断快照，再根据证据选择缓存/TLB、准入、调度或 Guest 启动假设。当前没有根因证明，不绕过 reset、不延长超时。外部到达、生产路径分解、等工作量探针/握手成本、真板频率/温控/计数器和随机重复四组仍缺，M1/M2 保持 false。

## 14. 私有 RAM 冷入口与首组真板时间链

本轮先增加 [复位失败观测](design/reset-failure-observations.md)，再根据真板现场形成 [私有 RAM 冷启动发布](design/aarch64-private-ram-cold-start.md) 修复。源码、失败、对照和最终成功均独立冻结。`results/reset-observations-audit.json` 核对递进故障证据，`results/native-timechain-audit.json` 只接纳独立分析通过的功能样本。

### 14.1 复位故障定位

`native-reset-diagnostic-board-cpu-32` 再次失败；复位运行的 API entry_count=7058，追踪捕获目标线程 7182 次入口边界，不能归为未调度。其追踪为已提交前缀，dropped=132796、incomplete=0，只作诊断。后续三个独立构建依次记录 IRQ 退出 PC、已保存的 Guest 系统寄存器和通过 GuestMemoryPort 的只读故障栈，没有增加硬件寄存器读写或访问私有 CPU 字段的接口。

同次 ELF 将停机 PC 0x40003234 定位为 `arch_system_halt`。Guest ESR=0x8600000f，ELR/FAR 均为 0x40055880，该地址是 `z_mm_lock` 数据对象；故障栈按实际 generated offsets 解码后，LR 也为该地址。`z_arm64_mm_init` 在开启 MMU/cache 后从栈恢复 x29/x30 并 ret，故障寄存器与该转换对应。异常解码以固定 Guest 源码和 [Linux ARM64 ESR 定义](https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/include/asm/esr.h) 交叉核对。逐步观测不能单凭地址就证明任意缓存或调度原因。

### 14.2 缓存状态控制与修复

`native-reset-cache-board-cpu-32` 保持 Guest ELF 不变，在无新 vCPU 的阶段仅对该受控 VM 的完整自有 RAM CleanAndInvalidate，不改 RAM 字节。两策略复位后均 Ready、各完成 32 次 CNTP/errors=0；套件通过且追踪 17191 条、无丢样。这支持完整 RAM 缓存状态影响复位结果，但该组离线分析因 8 个临时生命周期 Marker 混入原 128 个探针契约而拒绝，不能计作有效测量。原日志未修改，最终源码撤掉额外 Marker，保留原分析判定。

通用修复只在生产 `arch/aarch64/vm.rs` 增加 17 行：既有生命周期回收旧 vCPU、设备和访问能力后，初始化闭包在创建新 vCPU 前维护完整 allocator-owned RAM，包括 flat binary 外的 BSS/栈。保留/共享 RAM 不属于该分配所有权，继续自己的发布契约。临时 PC 日志、VM ID/128 MiB 特例及环境开关均从生产源文件精确撤回，最终代码不依赖研究环境变量。

`patches/aarch64-private-ram-cold-start.patch` 相对原 HEAD 的单文件增量已在隔离副本实际应用并逐字节匹配；测试/准备器/错误观测及平台参考另存为 `patches/reset-diagnostics.patch`，相对 `configs/reset-diagnostics-before.tar` 含 5 文件增量，同样实际应用校验。最终 axvm 21 项 Clippy 检查全部通过，未新增 unsafe、未合入或发布；冷启动维护成本尚未量化，合入前仍需领域审查。

### 14.3 最终有效基线

下列两组均使用最终源码、无临时诊断开关、32 项/策略、20 ms 逻辑周期、4096 轮、10 ms 任务预算、Linux CPU 工作量与有边界吞吐。两策略各 32 次 CNTP、errors=0、retired=1，任务全部有效且预算分类为 false；它们不是压力因子对照或优化收益实验。

| 运行 | 环境 | 有效任务 | 追踪 records/dropped/incomplete | 架构 counter |
| --- | --- | --- | --- | --- |
| native-private-ram-board-cpu-32 | RK3588 真板 | 64 | 16824 / 0 / 0 | 24 MHz |
| native-private-ram-qemu-cpu-32 | QEMU | 64 | 16947 / 0 / 0 | 62.5 MHz |

真板两策略的校准 offset 区间宽度约 1166.7/1458.3 ns，Linux 快照完成 4303/4324 批，elapsed 685390709/686511000 ns；这些是有控制成本的功能观察，不是纯探针开销或 DRAM 带宽。实际 Host DTB/FIT、Guest DTB/ELF/map/binary、配置、完整 Host 源码与测例包均冻结并核对身份。Counter 的 24 MHz 不是 CPU 工作频率固定的证明。

串口原始启动数据有一个非法 UTF-8 字节。`prepare-analysis-input.py` 保留原始日志，只在测量开始前允许 replacement；它逐字节确认从 VIRQ_MEASUREMENT 起到文件结尾完全不变，并保存两份 SHA。该规则通过后才执行原有九类分析及独立吞吐分析；测量区间中的非法编码直接拒绝，不修复或丢弃数值记录。

### 14.4 真板 A+B 的新拒绝

`native-private-ram-board-memory-sgi-32` 在同一源码上启用 SGI15 CPU2→0、2 ms/burst2/64 轮，以及 Linux CPU3 的 16 MiB/every1 内存工作量。两策略关键 CNTP 均为 32 次、errors=0；SGI handled 为 766/746、errors=0、skipped=0、joined/retired=1。但最终 `runtime trace lost records` 导致套件 exit=1，整组测量拒绝，不能把其中 64 条任务计入有效结果，也没有计算 I_AB。

当前失败输出没有打印 dropped/incomplete 的具体值或逐 CPU 占用，不能认定是哪一 CPU 溢出。源码确认压力 finish 在逐事件串口输出期间，Linux 与完成后等待 complete 的关键 Guest 仍运行，global trace 也仍开启；约 1500 条压力日志会把导出墙钟时间变成额外入口记录。下一步分离压力源回收/验证与日志输出，将拥有值报告保留到所有 VM 回收并冻结追踪后再导出，同时补充失败占用计数；不增加容量、不丢弃关键状态、不放宽丢样判定。

### 14.5 当前阶段门

已取得首组真板端到端功能样本，并用真实失败与同 ELF 控制推进复位问题。原 QEMU PL031 A+B 等待超时仍是独立未解释问题；本轮缓存修复不冒称解决该故障。新 A+B 组的投递成功也不替代完整性验收。

阶段 0～2 继续优先：先完成压力下的无丢样闭环，再量化等工作量探针/握手成本、核实实际 CPU 频率与温控及生产路径，固定参数做随机重复四组与交互不确定性。M1/M2 继续 false；没有真实耦合结论、联合控制实现或性能收益承诺。历史 audit 的 live-source 匹配只属于对应检查点，恢复历史代码应使用该次冻结包。


## 15. 压力报告冻结后导出

### 15.1 修复与独立顺序证明

旧 A+B 丢样组保留为拒绝数据。`Pressure::retire` 在原采样边界停源、join、撤销 IRQ 并执行全部原校验，返回只拥有事件 Vec 和标量的报告。两策略的 VM 全部退出、登记表清空且 `diagnostics::finish` 关闭记录写入后，才格式化压力报告。原追踪容量、SGI 容量和时序/计数/checksum、关键 IRQ、任务和围栏规则不变。失败时新增实际 dropped/incomplete 和逐 CPU 已提交前缀数量，不能将这些数量解释为逐 CPU 丢样。

设计与资源成本见 [压力报告延后导出](design/pressure-export.md)。独立 `audit-pressure-export.py` 在旧真实日志上稳定拒绝“导出先于最终 VM 退休”，红测为 `raw/pressure-export-order-red.log`；在新两组日志上验证所有压力事件晚于两组 VM 退休及冻结声明。该顺序是输出契约；实际压力是否完整仍由原分析器判定，不以新顺序标记代替功能验证。

### 15.2 真板与 QEMU 验证

| 运行 | 有效任务 | 追踪记录 | dropped / incomplete |
| --- | --- | --- | --- |
| pressure-export-board-memory-sgi-32 | 64 | 19018 | 0 / 0 |
| pressure-export-qemu-memory-sgi-32 | 64 | 18277 | 0 / 0 |

两组采用相同测试源码、Host 源码和 Cargo.lock。两策略各 32 次关键 CNTP 投递无错误；真板 SGI 760/746 次无错误、无跳期。QEMU SGI 1056/1028 次无错误，FIFO 报告 2 次压力周期跳期，保留实际强度而不伪装成精确频率；QEMU 仍只作功能验证。套件、9 类周期分析、Linux 围栏和独立导出顺序审计全部通过，完整输出为 `raw/pressure-export-{board,qemu}-analysis.log` 和 `results/*-export-audit.json`。套件退出码与离线验收分开记录，历史原始日志和失败数据不更改。本轮通过说明新流程可以完成该配置的无丢样试跑，不保证任意长度运行，也不解释原 QEMU mailbox 超时。

增量为 `patches/pressure-export.patch`，只改两个测试 Rust 文件，已在冻结的修改前源码副本独立应用并逐文件匹配。`cargo fmt --package axvm` 和 `cargo xtask clippy --package axvm` 的 21 项检查通过；归档同时保留全量源码/固件/Host FIT/DTB 和 Guest ELF。第 14 节 17 行生产 RAM 修复保持不变。当前校验入口为 `python3 research/cross-path-20261017/finalize-pressure-export.py`；旧 finalize 脚本描述各自历史检查点，不能作为当前工作树验收入口。

### 15.3 M1 的下一门

[后续测量门](design/m1-next-measurement-gate.md) 核对现有 AxVisor→AxVM 共享执行路径，并区分已经测到的事件与尚未插桩的 IRQ 分发/计时器同步阶段。相关源 SHA 保存于 `configs/m1-path-source-sha256.txt`。下一步保持相同任务与压力工作量，先量化 recorder enabled/disabled 的增量及残余握手成本；关闭模式不得伪造完整追踪或放宽原完整链分析器。频率/温度仍未核实，24 MHz 只表示架构计数器频率。重复随机化四组、交互不确定性、尾部和吞吐权衡尚未交付，M1/M2 为 false，不生成耦合或优化结论。


## 16. 等任务工作量的记录器配对对照

### 16.1 开关与拒绝契约

`VIRQ_RECORDING=on|off` 默认 on，仅写入 Host 资源，不改变 Guest C/CMake、任务工作量、周期、Deadline、IRQ 或 Linux 程序。off 在所有 VM 创建前通过原 finish 关闭记录准入，两模式均保留缓冲分配和编译钩子。原 IRQ/任务/时钟/围栏/退出校验仍执行。关闭模式没有 RuntimeSummary/ReadySummary，必须保留阶段不可用和 `trace_loss=null`，不能将动作计数冒充入口 Trace。

开销专用入口为 `virtualization/axvm/tests/analysis/analyze_virq_probe_cost.py`，复用原 ISR、任务关联、周期和底层 Linux 围栏校验。原完整链及依赖运行轨迹的完整围栏 CLI 仍拒绝 off；不放宽它们以容纳关闭记录。`complete_chain` 字段仅表示现有 T0/Ready/Running/GuestEntryBoundary/ISR/T6 验证范围，不表示提要要求的全部细分阶段或 M1 已完成。设计见 [记录器开销对照](design/recorder-cost.md)。

### 16.2 预定顺序与真实结果

在任何本轮真板数据产生前，固定种子 20261017 和 4 块平衡随机顺序：off/on、on/off、on/off、off/on。8 次 Host 启动各运行 Fair/FIFO 的 32 条任务，共 512 条有效观察；on 256 条无丢样，off 256 条只作任务观察。所有测试/Host 源码、Cargo.lock、工具版本、9 份 Guest/Host 固定输入逐字节一致，配置差异仅 recording。QEMU 另有 128 条功能观察，未用于硬件差值估计。

| 策略 | on-minus-off 平均响应差时钟区间 | 探索性配对 bootstrap 95% 区间 | Linux 迭代率相对变化均值 |
| --- | --- | --- | --- |
| Fair | +5.249～+8.167 µs | +3.458～+9.771 µs | -0.699% |
| FIFO80 | +5.653～+8.571 µs | +3.499～+11.050 µs | +0.192% |

逐块差值、DMR、辅助 Marker 包络及方法限制见 [配对试验报告](results/recorder-cost-report.md)、`results/recorder-cost-paired-summary.json` 和 `results/recorder-cost-paired-replicates.csv`。bootstrap 重采样整个块而非单条任务，10000 次、种子 20261018；仅 4 块，覆盖率未建立，不作显著性或收益判断。观测 DMR 为 0 不能保证未来 Deadline；32 条/策略/启动的 P99.9 退化为最大次序统计量，不建立 WCET/WCRT。

### 16.3 验证与复放

37 项分析测试、21 项 Clippy 检查通过，原任务拒绝测试确定性暴露并阻止“off 加伪完整性汇总”被接受；隔离副本把未知 trace_loss 改成 False 后，新开销测试也确定性失败，实际源码未改动。日志为 `raw/recorder-cost-analysis-tests.log`、`raw/recorder-cost-clippy.log`、`raw/recorder-completeness-red.log` 和 `raw/recorder-nullability-mutant-red.log`。每次 on 均经原 9 类周期分析和完整 Linux 围栏 CLI，每次 off 经专用入口复用围栏与任务规则，并保留完整链拒绝日志。

原始数据和身份在 `raw/recorder-cost-*`、`configs/recorder-cost-*`。预定方案为 `configs/recorder-cost-pair-plan.json`，控制器终态及全部已完成启动见 `results/recorder-cost-pair-status.json`；既有 plan 禁止盲目重启。新运行可给 `run-native-timechain.sh` 传入新 cohort 名并设置 VIRQ_RECORDING，不覆盖已有原始日志。

源增量 `patches/recorder-cost.patch` 只改 6 个测试文件，控制脚本增量另为 `patches/recorder-cost-controls.patch`；两者均在各自修改前归档副本应用并与实际源码匹配。生产 RAM 修复保持不变。复算依次执行 summarize-recorder-pairs.py、render-recorder-report.py 和当前 finalize-recorder-cost.py；各脚本均位于本目录，用 python3 运行。旧 finalize 脚本仅代表各自历史检查点。

### 16.4 剩余 M1/M2 门

[当前阶段契约](design/current-stage-contract.md) 明确缺失的 T1/T2、进入后端前的软件 T4 边界与跨核重叠，不简单累加有重叠的阶段。[平台观测缺口](design/platform-observation-gap.md) 区分原架构计数器、SCMI 策略值、PMU 送达频率和 TSADC 温度，以及 Host DTB/FIT 与板上 EL3 固件证据。当前没有对频率/温度作未测假设，也没有强制 OPP 或启用不相关驱动；开关差值仅是探索性关联。残余探针成本和现有生产路径观测仍须补齐，重复四组与耦合估计尚未开始，M1/M2 为 false。


## 17. IRQ 路由与低 EL 计时器同步分段

### 17.1 分段契约与范围

[设计与所有权](design/irq-stage-observation.md) 复用唯一 HostIrqCapture 和有界记录器，追加稳定编号 11～14 及 version=1 声明。以 CPU/INTID/T0 ticks 严格关联 Host 路由 begin/end；低 EL 从既有退出值传播关联标量，包围 synchronize_timer。没有新增物理 IRQ 所有者、硬件状态登记表或活动路径日志，原 IRQ/计时器/VGIC/错误传播与退休顺序保留。当前 EL 的对应 timer_sync 为 null；GuestEntryBoundary 仍是进入后端前的软件点。缺失、重复、孤立、未知版本和逆序均拒绝，旧日志保留旧能力，off 不能冒充完整链。

### 17.2 实际验证与源码身份

四次独立启动包含 QEMU 当前 EL、RK3588 真板 Linux 内存 + SGI 压力、QEMU Guest-running 低 EL，以及 QEMU off。共 256 条任务观察，其中 192 条有完整新分段、64 条关闭记录只作任务观察。三次 on 的 dropped/incomplete 均为 0；低 EL 每策略必须实际捕获低 EL T0，不能用合成记录替代。每次物理样本的唯一 IrqKick 均在自己的路由区间内。分平台/策略分布、计时器 null 及重叠分类见 [分段验证报告](results/irq-stages-report.md)。不同拓扑不混合作干扰或开销估计。

39 项分析测试和 21 项 Clippy 通过；增强的原 physical 拒绝测试先在旧实现上确定性失败，证据为 raw/irq-stage-contract-red.log。所有适用完整分析、周期、Linux 围栏与压力验收通过；off 额外保存 task/stages 拒绝日志。原控制器 run-irq-stage-checks.py 在低 EL 首试的装配失败处停止，计划/终态与原始失败均保留，未产生有效样本。新目录补齐既有 host-initramfs.toml 后，用 resume-irq-stage-checks.py 的 configs/irq-stage-recovery-plan.json 与 results/irq-stage-recovery-status.json 完成剩余两项；不覆盖或重启旧计划。每组真实原始字节、实际 Guest ELF/DTB、真板 Host FIT/DTB、配置、工具与完整源码均冻结，results/irq-stages-audit.json 验证四次 Host/测量实现一致及分析输入测量字节不变；测试源码树仅新增此前未使用的低 EL 装配清单，该配置差异显式列出。

增量为 patches/irq-stages.patch，共 15 文件，含新增 Host 模块和低 EL 专用四 CPU QEMU 配置；在 configs/irq-stages-before.tar.gz 的完整 Host/tests 副本应用并逐文件匹配。package-irq-stages.py 同时扫描 tests 和 src，避免遗漏新增 Host 文件。第 14 节生产 RAM 修复保持原 SHA。当前检查点入口为 python3 research/cross-path-20261017/finalize-irq-stages.py；第 16 节 finalize-recorder-cost.py 仅验证该历史时点，不能对本轮新源码直接运行。历史配对数据不更改。

### 17.3 解释边界与后续门

新增记录改变热路径开销，前一版本 +5～9 µs 不能移用于此版本；需要重新量化新记录器和残余握手成本。跨核 Ready/Running/ISR 可与路由区间重叠，分段不可机械相加；timer 与路由之间的间隙含 VGIC 保存等适配工作，不能单独归因。软件包围点不是纯寄存器操作成本，也不是引脚到达、硬件 ERET 或严格 WCET/WCRT。

频率/温度、其余 T0～T6 边界及随机重复四组、I_AB 不确定性与吞吐权衡仍未完成。M1/M2 继续 false，无耦合、优化收益或阶段 3～5 完成声明。该研究热路径变更在合入前仍需独立领域设计审查，本轮不提交或合入。


## 18. 独立于 CPU 调频的温度观测

### 18.1 唯一设备所有者与显式配置

[rk3588-thermal 设计](design/independent-thermal-observation.md) 将原调频模块内的 TSADC 探测/初始化、永久映射、保护校验与温度转换迁到独立 thermal 模块。CPU 调频包含并复用它，OTP/PVTM/regulator/OPP/governor 不因单独测温启用。新的公共查询只读、缺失/无效/失去保护时返回明确错误；原 cpufreq refresh 收紧阈值的行为仍由原 feature 使用。SoC 通道 0 与 A55 簇通道 3 分开命名，不混用 VM/逻辑 CPU 编号。

axtest-thermal 显式启用测温；默认配置不变。冷启动有 CRU/TSADC 初始化写入，继承的 CRU 核心还可能归一化 PPLL，不能称为整机完全被动插件。每个策略的 VM 创建前和全部退休后各查询一次两传感器，只保存值和计时包围区间，待全部 VM 退休与追踪关闭后批量输出。这些点不证明窗口最高温度或恒温，也不等价于固定 CPU 频率。

### 18.2 真实验证与拒绝

本轮 2 次有效独立启动共 128 条任务观察：真板 Linux 内存 + SGI 压力在启用测温时取得 4 组前后快照，默认 QEMU 保持温度不可用/null。两组完整链、周期、围栏、压力和 IRQ 分段验收通过，追踪 dropped/incomplete 均为 0。真板实际温度与两次查询的包围耗时详见 [温度观测报告](results/thermal-report.md)，仅作有边界的快照证据。

另一次 QEMU 开启测温但无 TSADC，在 VM 创建前按预期拒绝，0 条有效任务；没有补零、使用旧温度或跳过要求。原控制器对串口错误文本的匹配被 runner 插入的诊断行分割而中断，原计划、失败终态和原始日志保留。新恢复计划严格验证原错误的唯一诊断插入行，不改变原始字节或修复性能数据，之后只运行尚未执行的两组。证据为 configs/thermal-check-plan.json、configs/thermal-recovery-plan.json、results/thermal-negative-audit.json 和 results/thermal-recovery-status.json。

### 18.3 源码与测试证据

93 项定向 Clippy 和 40 项 Python 分析测试通过。当前源码的隔离副本只将自己的 std 测试清单限定 ax-driver，再运行原 cargo xtask test 的四个正式 profile；主树清单不改、未创建提交。隔离的“查询写寄存器”变异稳定失败，恢复后同一套件通过。原刷新阈值规则继续覆盖，但本轮未执行 CPU 升降频硬件测试，纯寄存器规则测试不替代真板设备证据。

增量 patches/independent-thermal.patch 共 16 文件，包括新增独立驱动、feature、测温记录/分析和完整运行侧车配置。在 configs/thermal-before-complete.tar.gz 的副本隔离应用后逐文件匹配；原始基线归档未改，补入的唯一 axvm manifest 来源核验见 configs/thermal-before-completion.json。三次启动的 Host/tests/驱动、feature manifest、锁文件与实际构建产物冻结，分析输入的测量字节保持原样。results/thermal-audit.json 验证身份和阶段边界，原 RAM 修复 SHA 不变。当前封存入口为 python3 research/cross-path-20261017/finalize-thermal.py；以前的 finalize 仅描述各自历史检查点，不能对当前驱动/测试源码直接运行。

### 18.4 剩余门

CPU 实际频率与窗口内环境覆盖仍缺失，当前 Guest 上下文会保存/恢复 PMCR_EL0，不能将跨 VM 的计数差直接当送达频率。本轮不写 PMU、不强制 OPP。新版本记录器/残余握手成本、其余 T0～T6 边界、EL3 固件逐次身份和随机重复四组仍未完成；旧 +5～9 µs 不能移用于新配置。M1/M2 继续 false，无耦合、联合优化或严格 WCET/WCRT 声明。高风险共享驱动在合入前仍需独立领域设计审查，本轮不提交或合入。


## 19. 保持 PMU 状态的逐核频率快照

### 19.1 所有权与观测边界

[短窗口设计](design/pmu-frequency-observation.md) 在现有本核 Pmu 所有者内增加受限只读回调与私有恢复守卫。PMCR 全局、counter、IRQ 或用户权限非空闲即无写入拒绝；仅核对过的版本 1/4/5/6 可借用，不复位全部 PMU，不写 OPP/SCMI/MDCR。恢复完整 64 位周期值、过滤器、原溢出与控制，原 PmuError 与调用方不改。Host PMCR 本来就保存恢复；本轮不声称修复其遗失问题。

axtest-frequency 显式启用。在每个策略的 VM 创建前、全部退休后，逐核固定亲和性，在屏蔽 IRQ 的约 2 ms 忙循环里用两组时间戳包围周期读；控制器亲和性随后恢复 CPU0，输出在全部 VM 退休和追踪关闭后。所得区间假设单 tick 的参考分辨率并计入一个周期粒度，依赖公布的参考频率。真板紧邻时间戳正差值全部为 7 ticks，单 tick 有效分辨率尚未验证，表中细小区间不能视作完整物理误差边界；约 816 MHz 仅为名义参考下的 PMU 快照估计，不是统计置信区间或运行窗口恒频保证。测频会预热核心、延迟本核 IRQ 并可能影响固件策略；温度在每组测频前查询。

### 19.2 实际验证与身份

[快照报告](results/frequency-report.md) 和 [原始值汇总](results/frequency-snapshots.csv) 记录三次独立完整链启动的 192 条任务观察。真板 Linux 内存 + SGI 压力取得 A55 四核的 16 个频率快照和 4 个温度快照；QEMU 开启取得 16 个功能快照，关闭保持不可用。三组完整链、周期、围栏与 IRQ 分段验收通过，dropped/incomplete 均为 0；QEMU 数值不作为物理频率证据。

75 项 Clippy、41 项分析测试通过。既有 PMU 正式用例在四核 Cortex-A53、四核 max QEMU 与八核真板通过，覆盖版本 1/6/4。八核只是独立寄存器功能测试，论文配置仍是四核。暂时截断恢复高 32 位后同一 QEMU 用例稳定失败，finally 恢复原字节后通过；没有其他实验在变异期间运行。较新未支持版本尚无真实执行证据。分析套件首次失败因拒绝输入未命中，修正输入后原规则通过，旧失败日志保留。

configs/frequency-check-plan.json 与 results/frequency-check-status.json 保存一次性计划及终态，不盲目重启。每次冻结 Host/tests/ax-cpu/驱动、feature、锁文件及实际镜像/DTB/FIT，measurement 字节未改；审计为 results/frequency-audit.json。真板同 tick 端点暴露初版分析缺少粒度边界，全部原计划结束后才修改两个分析文件，以同一测试先红后绿并重算三组数据；原源码及旧输出完整保留，差异见 configs/frequency-quantization-correction.json，旧数值已被替代。17 文件补丁 patches/frequency-cycles.patch 在 configs/frequency-before.tar.gz 的完整副本隔离应用并逐字节匹配，原 RAM 修复与 Host 热路径源码不变。当前封存入口为 finalize-frequency.py，以前 finalize 仅描述各自历史时点。

### 19.3 仍未完成的门

快照不证明活跃 VM 窗口内的频率、最高温度或固定 OPP；参考计数器有效分辨率和更新语义须先核对。新配置探针/残余握手成本、其余 T0～T6 边界、EL3 固件逐次身份、随机重复四组及运行级 I_AB 不确定性仍未完成，旧版本成本不能移用。M1/M2 继续 false，无耦合、优化收益或严格 WCET/WCRT 结论。高风险共享硬件 API 合入前仍需合格领域设计和 unsafe 审查，本轮不提交或合入。


## 20. EL2 连续计数读与分辨率敏感性

### 20.1 同一所有者内的只读序列

[设计与权威语义](design/counter-increment-observation.md) 在原 axtest-frequency 固定 CPU、IRQ 守卫和 VM 创建前/退休后位置，增加 physical、virtual 与无额外 ISB 的 physical_raw 三类序列，每类 256 个完整原始值。采集在周期计数借用之前；不新增全局状态、PMU 所有者或 feature，不读写 Secure 计数控制、参考频率、比较器、GIC 或 OPP。数组随原快照保存，全部 VM 退休与追踪关闭后才输出。默认关闭显式声明没有序列。

新分析入口严格校验版本、完整键集合、时钟、u64、物理包围与任务窗口。串行化序列逆序或无进展拒绝；virtual 不假定 offset=0，raw 只作读序诊断并保留逆序统计。有限样本的增量、GCD 和最小正值不自动成为硬件最大步长或校准证明。

### 20.2 实际结果与验证

[连续读报告](results/counter-report.md)、[完整序列](results/counter-series.csv) 和 [频率敏感性](results/counter-frequency-sensitivity.csv) 记录三次独立完整链启动。真板四核 Linux 内存 + SGI 与 QEMU 开启各取得 48 段、12288 个原始读数；默认关闭无序列。共 192 条有效任务观察，完整链、周期、围栏、IRQ 分段与新序列验收通过，dropped/incomplete 均为 0。QEMU 只作为功能证据，不混合作物理分辨率推断。

29 项 Clippy、42 项分析测试通过。临时移除串行化逆序拒绝时同一测试稳定失败，恢复原字节后通过，见 configs/counter-reversal-contract.json。五文件增量 patches/counter-increments.patch 在 configs/counter-before.tar.gz 的副本隔离应用后匹配。CPU 核心、Host 热路径、PMU 恢复、驱动、压力实现、manifest、锁文件及原 RAM 修复不变；每次冻结相关源码和实际构建产物，measurement 原始字节不改。

configs/counter-check-plan.json 与 results/counter-check-status.json 保存一次性计划及终态；禁止盲目重启。当前审计为 results/counter-audit.json，封存入口为 finalize-counter.py；旧 finalize 只描述各自历史时点。

### 20.3 解释与后续门

Arm 规范允许减少可见计数更新而保持名义时间尺度，不能从 CNTFRQ 推定每次只更新一 tick。本轮保留三个模式的原始分布及 q=1/观察 GCD 的敏感性，不认证硬件配置、未来最大更新步长或参考时钟准确度，也不回填第 19 原始结果。后续性能比较应报告名义参考、观察粒度及假设，不能冒称绝对物理误差保证。

新配置记录器和残余握手成本、其余阶段边界、固件逐次身份以及随机重复四组、运行级 I_AB 不确定性仍待完成。[下一步开销对照](design/current-probe-cost-plan.md) 已据源码将差值范围明确为记录操作，包含被门控的时间戳、预留和写入，不能只称纯内存写入。M1/M2 继续 false，无稳定耦合、联合优化或严格 WCET/WCRT 结论。本轮不提交或合入。


## 21. 当前版本记录操作的八对真板对照

### 21.1 范围与重复单位

[协议与范围校正](design/current-probe-cost-plan.md) 以版本 2 声明 recorder_operations，涵盖随开关门控的内部时间戳、IRQ 守卫、writer 登记、预留与写入。旧 recorder_writes 声明兼容但不保证纯内存写入成本；独立任务/IRQ 计时、入口检查、编译 hook、邮箱和 Linux 围栏等残余项保留。本轮不改 Host 热路径或 PMU 核心。

两组 QEMU on/off 功能验证后，按运行前种子 20261021 的平衡顺序执行 8 个独立真板启动对；16 次启动共 1024 条任务观察。on 的 512 条有记录并通过既有物理任务链入口，off 的 512 条只作任务观察，完整链和 IRQ 阶段必须拒绝，trace_loss 保持未知。频率、温度和计数序列两模式均启用，其他工作量与输入相同。QEMU 的 128 条任务不进入性能估计。

### 21.2 统计、身份与实际结果

[开销报告](results/recorder-ops-report.md)、[逐对结果](results/recorder-ops-paired-replicates.csv) 和 [环境快照](results/recorder-ops-environment.csv) 给出共同计划释放→Guest 完成端点的 on−off 均值区间、以完整启动对为单位的 10000 次 Bootstrap、Guest 执行差、Linux 吞吐、尾部和观察 DMR。8 对不是 256 次独立重复；百分位包围不认证小样本覆盖率或物理时钟误差，P99.9 在每策略/模式 256 个任务时等于最大次序统计量。差值可为负，不预设正开销或优化收益。

29 项 Clippy、42 项分析测试通过。准确声明的同一行为测试在旧解析实现上先失败，更新后通过，legacy 及错误版本组合的规则保持。独立统计测试通过；隔离副本膨胀到每任务独立重采样时稳定失败，主源码不改。三文件补丁 patches/recorder-operations.patch 在 configs/recorder-ops-before.tar.gz 的副本隔离应用后匹配。每次冻结相关源码、工具、输入和实际产物；原测量字节不改，真板 FIT/DTB 按本次启动日志的实际路径核对，不把其他缓存文件当作使用证明。

一次性计划与终态为 configs/recorder-ops-plan.json、results/recorder-ops-status.json，不盲目重启。审计为 results/recorder-ops-audit.json，当前封存入口为 finalize-recorder-ops.py；旧 finalize 仅描述各自历史时点。

### 21.3 剩余 M1/M2 门

快照不是运行窗口恒频、最高温度或固定 OPP 的保证，U-Boot/BL31 逐次身份仍不完整。记录操作差值不是全部探针成本，T4 仍是软件进入边界，阶段重叠和关联比例须准确报告。M1/M2 保持 false。下一步审计同一链中的实际阶段与残余成本，然后进行交错/随机重复 0/A/B/AB，按运行级均值估计 I_AB，不以分位数非加性证明耦合；仅在稳定交互和机制证据支持后进入后续优化。本轮不提交或合入。



## 22. 当前版本阶段基线与随机四组

### 22.1 阶段关联

[阶段报告](results/stage-baseline-report.md)、[阶段图](results/figures/stage-baseline.pdf) 与 `results/stage-baseline-summary.json` 只汇总原八次真板 on 启动。严格唯一子集、歧义分母、实际重叠、原 offset 仿射链与因果窗截断分别保留；Host route 不重复加入串行链。软件 T4 和线程 T6 不冒称硬件 ERET 或设备输出。

### 22.2 四组重复

[四组报告](results/factorial-report.md) 来自新八块32次独立真板启动，共2048条任务观察。种子、Williams顺序、完整运行身份和派生产物均绑定原计划；首次失败停止，不静默替换坏结果。I_AB 按运行级均值和完整块重采样，尾部、DMR及Linux吞吐分列。CPU与内存工作负载的迭代率不能跨工作量解释为优化收益。固件只读构建文本按实际可见性保留，不作固件二进制认证。

### 22.3 复现与未完成项

`factorial_runner.py`、`summarize-factorial.py`、`plot-phase12.py` 和 `finalize-phase12.py` 分别负责一次性编排、完整块统计、标准绘图与归档。绘图环境依赖为 `configs/phase12-plot-requirements.txt`；源码增量与独立应用核验见 `patches/phase12-analysis.patch` 和 `results/phase12-patch-audit.json`。原开销实验与本轮源码冻结不改，所有原始失败/测量字节保留。

本检查点不等于阶段0～2全部验收；完整剩余项见 `results/phase12-checkpoint-audit.json`。第二种CPU拓扑、环境与固件完整身份、残余探针成本、A/B强度及相位敏感性仍须补齐，M1/M2保持false。只有稳定交互后才验证机制，机制成立后才实现联合控制；不将分位数非加性或最大观测值当作耦合或严格WCET/WCRT证明。
