# 严格追踪容量 v2 Task1 独立 Spec 审阅

结论：**PASS，无阻断项**。只认可新候选的离线准备，进入独立 Quality 审阅和 Root 复制核验；不构成板卡启动批准。

绑定实施报告 SHA `74eace0f3fd2a8611fcb49fe981a754bb722104dc89efd737acddf81a5087429`，设计 SHA `5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd`，现行计划 SHA `54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27`。候选 freeze SHA `6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`；新 702 SHA `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，tar SHA `072c67c53641c3428ddfaa031692a506443105b0a023376dff90e307e1f8f29d`。

现时逐项核验新/父 702 项字节与模式、tar 全部成员、执行与归档两处 69 项冻结成员，以及原 155 项归档索引。唯一 Rust 差异是容量 16,384→65,536 和两行英文说明；701 项、Cargo.lock、三份控制 TOML 不变。完整 9,642 普通树身份清单仅此一项变化；现时完整普通树与整 cache 不重复扫描，采用已保存的真实 ready/finalizer 全核记录，并精选实际入口核验。原归档含索引 104,178,056 B，低于 1 GiB。

controller 逐字节只改输出根 v1→v2；capture 与已 Spec、Quality、Root 接纳的 `e1e573ed…a14b2` 同字节。record_at、initialize、finish、原子序、IRQ 守卫、loss ensure 与事件导出保持；输入仅替换必要新路径与新身份，900/920/10/30 秒、512 MiB、压力及生产相位界不变。新 cache 仅 13 项入口/metadata 做已登记 prefix 替换，模式不变；新 Python prefix、cmake 模块和所选 binary 均在新 cache，系统解释器仍为 `/usr/bin/python3.12`。

原始 fmt、项目 xtask Clippy 收据与完整输出身份吻合，真实 wait 均为 0；Clippy 29/29、0 failed、0 skipped。Python -B 和直接新 cmake 入口真实 wait 均为 0。恢复固定资产后的原正式 ready0、错误 source2、准确 freeze 下无效 approval2 使用禁止写入/网络/子进程/signal 的 AUDITED_ENTRY，target 前后相同且无新 once/单项输出；未复跑 ready 或重扫主96。

初始 prepare guard 误排合法源码、首轮固定 kernel/base 缺失导致 ready2/外层1均保留。Root 以归档同 SHA/bytes/mode 恢复原路径，原因 unknown，未下载/重建或回填历史。慢 finalizer 的 Root 精确 proc/pidfd SIGTERM 事件单列：原统一 exec 实退143，无自定义 Popen.wait；原加载脚本注明 reconstructed，修正版新目录实际 Popen.wait0。不能声称整轮无 proc/signal；本审阅没有读 proc 或发 signal。

[独立检查](../raw/strict-native-phase-v2/task1/spec-review-v1/checks-after-gcc-link-v1.json) 170 项全部通过，[实际父 wait 收据](../raw/strict-native-phase-v2/task1/spec-review-v1/receipt-after-gcc-link-v1.json) 为 0。首轮审阅器将系统 GCC alias 误按源码/cache 链接合同比较，已保留首轮 wait1 和脚本快照；现按原 external_inputs 的解析后 binary 合同核验，生产门未改。

本审阅未运行 Rust 构建、QEMU、板卡、正式统计、Guest 或旧测试。新 AB1/AB0/0 均未执行，旧 AB1 仍失败、旧 release=unknown；normal_host、真板容量修复、M2、Joint、goal 仍 false。四 CPU 槽估算增至 10 MiB，不保证真实零丢样；后续须补新测量版本 matched recording-on/off 开销。
