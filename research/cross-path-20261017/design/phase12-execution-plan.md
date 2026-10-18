# 阶段基线与四组实验执行计划

> 执行流程：使用 `superpowers:executing-plans` 逐项验证；以当前工作树和原始运行结果为事实来源。冻结中的 Host、Guest、分析器和控制脚本不改动，不提交或合入既有研究改动。

**目标**：依据 V3.0 阶段 0～2，用当前版本完成开销对照、阶段延迟基线和随机完整块的四组真板实验，保留阴性、失败和不可测结果。

**结构**：复用 `run-frequency-timechain.sh`、原完整链/环境/压力分析器和冻结输入；新增逻辑仅在研究目录中处理阶段汇总、实验编排及运行级统计。每次独立 Host 启动依次包含 Fair 和 FIFO，两个策略分别分析。

**工具**：项目固定 `cargo xtask ktest board`、Python 3 标准库、原始串口日志、SHA-256 配置及产物快照。

## 1. 基线证据

基线取 `recorder-ops-plan.json` 指定的八次 on 启动，必须等完整原计划成功、`finalize-recorder-ops.py` 封存后再生成最终汇总。运行中只对已验收启动验证分析流程，不能将中期数据升级为最终结果。

### 1.1 阶段边界

复用 `analyze_virq_stages.analyze()`、`analyze_virq_runtime.analyze()`、`analyze_virq_ready.analyze()` 和 `analyze_virq_task.analyze()`，按同一日志的 `(policy, sample)` 对齐。T0 为现有 pre-IAR 软件点；T1 为 Host route；当前 EL 的 T2 为 null；T3 包含 Ready→Running；T4 是 backend 调用前的软件边界；T5 是 Guest C ISR；T6 是已知答案线程任务完成。

可加分解以 T0→IrqKick→WakeBegin→Ready→Running→GuestEntryBoundary→ISR→ISR end→Task start→Task end 为链，跨域端点保留同一 offset 的相关性；Host route 的全长另列，不加入该链。不能单凭原 `runtime.full_chain` 推定唯一：原程序允许首个 Wake/Running 与最后一个 Entry 包围包含抢占的区间；新分段须核对候选数和线程代际，只在唯一子集作严格分解，其余样本保留状态和分母。

代数一致性在原始 ticks 的仿射表达式中核验，同一 offset 项只计算一次，再报告纳秒外取整残差。原 ISR/T6 分析器还分别与 Host 因果窗相交；不得把这些已截断或已取整的上下界直接相加并声称精确相消。因果截断后的端到端范围与原始 offset 链包围分别输出，不能把各段分位数相加，不能补零或任意选一条。

### 1.2 成本与环境

`recorder_operations` on−off 仅量化被门控的记录路径；独立校时、邮箱、Guest 时间戳和围栏仍存在。Marker、时钟握手宽度和 Host 完成观察滞后可描述残余扰动的包围与观察质量，不能将其相加称为已隔离的总探针成本。

PMU 和 TSADC 为窗口前后快照，不认证固定 OPP、窗口内恒频或最高温度。新 `run-factorial-timechain.sh` 使用同一测量配置及独立的板卡运行侧车，仅增加只读 `uboot_cmd=["version"]` 和 `RUST_LOG=info,uboot_shell=debug`。已核对 Cargo.lock 锁定的 ostool 0.30.3/uboot-shell 0.2.9：`wait_for_reply()` 和 `wait_for_interrupt()` 在 DEBUG 下记录真实串口行，既有 runner 默认丢弃的版本回复因此可被归档。若某次看不到 U-Boot/BL31 构建文本，字段保持缺失；文本一致也不等于固件二进制完整身份。首次观测模式固定后如后续文本变更或消失则停止。旧开销实验与原控制脚本不改。

逐次固件完整身份缺口与软 T4、无设备输出边界仍明确列为未完成项，不将有限分辨率隐藏，也不把绝对物理误差认证当作无限推迟因素实验的理由。

## 2. 四组协议

在任何新四组数据产生前，保存唯一计划及种子；当前轮与既有单次功能验证、开销对照分别归档，不能把历史启动填入正式完整块。缺失平台字段意味着受限实验，不能冒称全部环境验收完成或因果机制已证明。

### 2.1 固定因素

沿用当前四核 A55 配置：CPU0 服务和关键 PPI30，CPU1 关键 Guest，CPU2 SGI 发送者，CPU3 Linux；4096 轮已知答案任务，blocked 等待，20 ms 计划周期，10 ms 任务预算，每策略 32 条任务，记录、频率/温度/计数读和 Linux 围栏均开启。

四组只改变 `scenario` 和 `irq_pressure`：0=`linux_cpu/off`，A=`linux_cpu/sgi`，B=`linux_memory/off`，AB=`linux_memory/sgi`。A 使用既有 INTID15、2 ms 周期、每批 2 次、64 轮 handler；B 使用 16 MiB 工作集、每批内存访问。0 的 Linux CPU 基线本身仍访问内存，B 是替换为已校验内存压力工作负载，不声称完全无内存访问。

### 2.2 随机重复与失败

预定八个独立完整块，每块包含四次 Host 启动，各条件在四个顺序位置各出现两次；以四行 Williams 顺序各重复两次，用固定种子打乱条件映射和块顺序。块内每种不同条件的有序相邻对各出现两次，减少某条件总跟在另一条件之后的混杂，但不声称消除跨块温度趋势或其他残留。每次必须通过工作量、退休、唯一关联、零追踪丢失和环境/压力配置核验，核对固定源码、工具、Host/关键 Guest 输入身份，以及 Linux 同工作负载内的镜像身份。

`identity_for()` 只规范化已验证的 Linux VM 工作负载名称差异，资源字段仍跨四组比较，原 VM 配置哈希按工作负载固定。Host FIT 每次保留原 SHA 并绑定真实启动路径；同条件的内容比较仅由 `normalized_fit_sha256()` 将根 `/timestamp` 的 4 字节置零后散列全部字节，不忽略 payload 或其他属性。已从锁定 fitimage 0.1.7 的 `standard_dt_builder` 和三次原真板 on 镜像核实唯一差异为打包时间；不能直接要求整 FIT 的 SHA 每次相等。

遇到任意构建、运行、正确性、丢样或身份失败即停止控制器，保留失败启动和未完成块，不静默重跑、不替换坏值。控制器存活则观察同一 PID；终态失败才能根据实际原因另立恢复计划，不能仅因观察超时重启。开始前确认现有开销实验与封存进程成功结束，避免并占板卡。

首个 `factorial` B 启动在测量前因新配置目录缺少 `guest-builds.toml` 和 `host-initramfs.toml` 失败，原计划与零接纳终态保留。已对照 `ktest::prepare_axvisor_ktest_payload()` 和 `axvisor::test::prepare_guest_builds()` 确认，两类清单均以实际 run-config 所在目录解析；不能只移动板卡 TOML。失败控制代码完整保存在 `configs/factorial-failed-controls.tar.gz`，原补丁另存 `patches/phase12-analysis-failed.patch`，原因与哈希为 `configs/factorial-infrastructure-failure.json`。

恢复方案从原 frequency 目录逐字节复制两个清单，并在板卡分配前由 `validate_runtime_sidecars()` 验证一致性。通过 `python3 research/cross-path-20261017/run-phase12-pipeline.py --recovery` 运行新的 `factorial-recovery` 队列；新计划/状态文件与全部运行名称独立，沿用原种子和八块顺序，不能把旧失败补成成功，也不把失败启动当性能样本。Host/Guest 测量实现未变，版本文本仍按真实捕获保留。

## 3. 统计交付

`analyze_virq_interaction.summarize_replicates()` 的现有完整块统计可复用，但须把 Host/Guest 偏移上下界通过 `AB−A−B+0` 向外传播；重采样同一完整块的下界和上界。主指标为计划 release→Guest task end，另列 T0→T6，以揭示排队和触发前等待是否掩盖路径变化。

### 3.1 不确定性与尾部

每策略每条件先求单启动的均值端点，再逐块求交互端点，用完整块的 10000 次 percentile bootstrap 给出经验区间。保留各块、各顺序、前后半块和删除一块的敏感性；八块不保证区间覆盖率或足够功效，区间跨零应报告当前条件下无稳健证据，不能升级为“完全无耦合”。

每条件另报均值、P50/P99/P99.9、最大观测值、时钟分类 DMR 和样本/启动数。每策略每条件 256 个任务时 P99.9 等于最大次序统计量；不当作 WCET/WCRT，不用分位数非加性证明耦合。Linux CPU 迭代率与内存工作负载迭代率分列；逻辑读写吞吐不是 DRAM 总线带宽，不跨不同工作负载解释为同工作量性能收益。

### 3.2 后续门

阶段 0/1 缺口按实际证据保留，M1 不由脚本运行成功自动置 true。M2 也不由区间排除零自动置 true：需要条件敏感性和机制解释。只有交互稳定后才另立相位/资源/路径对照；机制证据成立后才设计可回滚协同优化，当前不新增控制器。

## 4. 执行清单

以下步骤的状态以实际输出更新，不修改原开销计划的停止规则。

### 4.1 离线准备

- [x] 用已验收原始日志调用原分析入口，核实阶段关联率、跨核重叠和可加链。
- [x] 新增研究目录中的阶段汇总；先以合成非重叠/重叠区间验证代数分解，再以真实日志验证；缺失或歧义必须拒绝或显式计数。
- [x] 准备随机完整块编排与上下界交互统计；测试保护成块重采样、符号传播与失败停止，不复制已有底层解析测试。
- [x] 独立审阅本计划和新增分析边界，修正影响结论的缺陷。

### 4.2 实际运行

- [x] 核实原 18 次启动全部成功及原 finalizer 终态；生成当前记录操作报告和八次 on 基线。
- [ ] 固定四组计划、源码/工具/输入身份和全部测量限制；在指定主机顺序执行 32 次真板启动。
- [ ] 汇总原始 Trace、环境、阶段、均值交互及不确定性、尾部、DMR 和 Linux 吞吐；核验全部输出与引用及 SHA。
- [ ] 按完整论文目标审计 M1/M2，报告尚缺或否定证据；未通过时不声称阶段 3～5 完成。
