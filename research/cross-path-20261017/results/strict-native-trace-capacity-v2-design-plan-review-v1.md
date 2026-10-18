# 严格相位追踪容量v2设计与计划独立审阅

设计通过，实施计划需修改后复审。唯一阻断项是新cache副本仍可经绝对shebang执行旧cache解释器和CMake。本报告不批准Task1实施或任何硬件启动；完整证据与准确输入身份见[审阅JSON](strict-native-trace-capacity-v2-design-plan-review-v1.json)。

## 1. 设计结论

设计以最小容量改动准备新的测量版本，正确保留旧失败和研究门。审阅先核设计，再对照实施顺序和真实工具入口。

### 1.1 容量和资源边界

实际`diagnostics.rs::record_at()`在缺CPU缓冲区和越过容量时都计`DROPPED`。旧AB1保留22343、dropped19839、incomplete0，CPU3保留16384达到原容量；实际`VIRQ_RUNTIME`逐事件行数为0，不能把occupancy当成导出，更不能把所有丢样唯一归因CPU3。设计没有扩大旧证据的结论。

四CPU的40B槽从2.5增至10MiB计算正确。按AArch64字段估算，满262144条`Event`副本约14MiB，槽与副本载荷约24MiB；若`Vec`翻倍扩容不能原位完成，载荷峰值示例约31MiB，另有allocator/Vec开销。旧Host日志提供多GiB free和4CPU观察，不是新运行分配保证。`initialize()`、原子序、IRQ守卫、`finish()`及loss ensure均保留原行为，容量变化后还须新测开销。

按最长kind、20位u64和CRLF保守估算，Runtime行最多170B，四CPU满容量约42.5MiB；1500000 baud、8N1的理想串行时间约297.10秒。旧失败driver399.53秒加该量级约696.62秒仍不是新总耗时上界，格式化、接收、调试日志、构建和申请均有额外成本。继续保持900/920秒和超时失败门是合理的有界候选选择，不能承诺本次一定通过。

### 1.2 证据与研究边界

新702身份、其余701份不变、完整普通树与工具/cache重新冻结、旧96和AB1材料不回写、同版本追踪开关、正常功能与legacy完成后再正式分析均明确。旧`release=unknown`保持；新宿主服务可用性只支持新申请条件。M2、Joint及goal仍未完成。

## 2. 实施计划结论

计划保留离线与真板分门，正确要求真实`cargo fmt -p axvm`、`cargo xtask clippy --package axvm`，随后冻结新身份。它还需要补足真实缓存入口的迁移，才能实现宣称的新独立候选。

### 2.1 阻断项

`P2-CACHE-RELOCATION`位于计划19、25、28、30行。旧批准cache的`venv/bin/cmake`首行是`#!/tmp/strict-native-phase-tools-kevemo32/cache/vcpu-runtime-cache/venv/bin/python3`，ctest、cpack、pip也相同。真实`virq/prepare.py::build_guest()`直接执行`tools_dir/cmake`，该shebang会把新副本交给旧解释器；`cmake`模块再从旧site-packages定位其二进制。局部核查已验证四个入口与旧manifest SHA/bytes/mode匹配。

只copy cache和生成新manifest不能排除这条隐藏旧目录依赖。修订计划应要求只在新私有cache中扫描并最小重定位旧前缀的实际shebang及有关venv配置/激活metadata，保存准确小diff与新manifest。冻结前用真实只读局部入口记录新解释器`sys.prefix`、cmake模块及实际二进制的解析路径，证明实际使用新cache；旧cache不改，不通过新增Cargo配置绕过。该证明不要求重跑旧cleanup替身矩阵。

### 2.2 其余步骤和继承范围

原`native_once.py`只有一处v1输出根字面量；source/target/cache/tools身份由`inputs.json`及manifest读取，因此controller仅改输出根可成立，路径与身份输入仍须全部重新冻结。`Cargo.lock`属于702，fmt/Clippy后必须重核其余701和完整普通树，不能默默接受额外源码变化。允许的Cargo bookkeeping应与不可变build input分开记before/after。

新捕获器与原工具的`capture_native()`、`verify_static()`、`verify_rootfs()`、`parse_newc()`、`init_from_source()`、`verify_fdt_transform()` AST相同，继承这些未改门的依据合理。新运行必须重新取得全部真实工件尾门通过；旧完整post-exit通过不自动证明新工件。核查时捕获修订Spec的实际`decision=PASS`，指定Quality报告尚不存在；计划保留完成Spec→Quality及Root准确身份鲜核的前置，没有提前授予批准。

容量是有界参数变化，不新增常量镜像或host录制器模型测试是合理选择。新真实三项功能门仍必须覆盖全局零丢样、完整事件、双策略/任务、同代严格时间、退休、suite、退出和释放。旧offline-check的“主96未完成”判据不可直接复用，计划已明确这一点。Task1双审及Root复制核验后，AB1→AB0→0仍逐项Root批准，每项最多一次；任何失败、不完整或本次释放未知都停止余项。

## 3. 绑定与核查记录

本轮只新增本报告和指定局部收据，没有实施修复。用户新的Git提交授权由Root另行处理，不把文档历史措辞“不进行Git写入”作为技术阻断。

### 3.1 准确版本

本轮结论只绑定以下原文档字节；修订后须重新绑定并复审。

- 设计SHA256：`5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd`。
- 计划SHA256：`c93b2359e0c4c418bdd9ae1dd9847314881783bc2be0e138ec149714a8c7d83b`。
- 捕获修订SHA256：`e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2`，使用前仍需实际双审及Root鲜核。

### 3.2 实际执行与限制

[局部核查](../raw/strict-native-phase-v2/design-review-v1/local-checks.json)由真实父进程持有原直接子进程并调用`subprocess.Popen.wait()`，结果为0，见[执行收据](../raw/strict-native-phase-v2/design-review-v1/local-checks.execution.json)。这个0仅证明取证断言成立，计划结论仍为需修改。源码锚点见[选取片段](../raw/strict-native-phase-v2/design-review-v1/selected-excerpts.json)。

没有Git写入、Rust格式化/构建/Clippy、板卡、QEMU、proc、signal或正式相位分析，没有重hash全96或cache，也没有访问用户提过清理的三个/tmp目录。内存和串口数字均为明确假设下的静态量级核查。512MiB在现有capture里按17个输入工件累加，不含raw log或提取副本；实际总归档仍须另登记。正常功能、M2、Joint和goal仍未通过。
